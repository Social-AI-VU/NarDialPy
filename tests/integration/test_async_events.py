"""End-to-end integration tests for the async event / interruption system.

Three scenarios are exercised in a single file to confirm that all event-system
layers work together against real asyncio scheduling:

1. **TimerSource → BETWEEN_DIALOGS handler** — a timer fires during the first
   dialog and its handler runs before the second dialog starts.

2. **BackgroundLLMSource → BETWEEN_MOVES + PAUSE** — a background LLM call
   completes during the first move of a two-move dialog; the handler dialog
   runs, then the interrupted dialog resumes from Move 2.

3. **wait_for_button resolved by a live EventSource** — a custom source emits a
   ``button_press`` event after a short delay; the ``wait_for_button`` move
   resolves to the correct outcome and the right branch is taken.

Infrastructure required: filesystem only (no Redis, no SIC services).

Run with::

    pytest tests/integration/test_async_events.py --integration
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nardial.events.source import EventSource
from nardial.events.sources.background_llm import BackgroundLLMSource
from nardial.events.sources.timer import TimerSource
from nardial.events.specs import EventHandlerSpec
from nardial.events.types import Event, InterruptLevel, ResumePolicy
from nardial.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_agent():
    """AsyncMock agent stub compatible with DialogRuntime's async move dispatch."""
    agent = MagicMock()
    agent.say = AsyncMock()
    agent.ask_yesno = AsyncMock(return_value="no")
    agent.ask_open = AsyncMock(return_value="")
    agent.ask_options = AsyncMock(return_value="")
    agent.play_audio = MagicMock()
    agent.play_motion_sequence = MagicMock()
    agent.play_animation = MagicMock()
    agent.personalize = MagicMock(return_value=None)
    agent.extract_topics_with_llm = AsyncMock(return_value=[])
    # Device stub that returns no hardware sources.
    device = MagicMock()
    device.get_event_sources = MagicMock(return_value=[])
    orchestrator = MagicMock()
    orchestrator.device = device
    agent.orchestrator = orchestrator
    return agent


# ---------------------------------------------------------------------------
# Scenario 1 — TimerSource fires BETWEEN_DIALOGS
# ---------------------------------------------------------------------------

_TIMER_DIALOGS = [
    {
        "id": "first_dialog",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [{"type": "say", "text": "First"}],
    },
    {
        "id": "timer_handler",
        "type": "functional",
        "functional_type": "farewell",
        "moves": [{"type": "say", "text": "Timer fired!"}],
    },
    {
        "id": "second_dialog",
        "type": "functional",
        "functional_type": "farewell",
        "moves": [{"type": "say", "text": "Second"}],
    },
]


@pytest.fixture
def timer_dialogs_file(tmp_path):
    path = tmp_path / "timer_dialogs.json"
    path.write_text(json.dumps(_TIMER_DIALOGS), encoding="utf-8")
    return str(path)


async def test_timer_source_handler_runs_between_dialogs(timer_dialogs_file):
    """TimerSource fires during the first dialog; its handler runs before the second.

    The timer is set to 20 ms.  The first dialog's say move sleeps 50 ms so the
    timer event is guaranteed to be in the bus queue when the dialog loop drains
    BETWEEN_DIALOGS events before starting the second dialog.
    """
    agent = _make_agent()

    # Make the first say call take 50 ms so the 20 ms timer fires during it.
    original_say = agent.say

    async def slow_say(text):
        if text == "First":
            await asyncio.sleep(0.05)

    agent.say.side_effect = slow_say

    sm = SessionManager(
        session_agenda=["first_dialog", "second_dialog"],
        agent=agent,
        dialog_json_path=timer_dialogs_file,
    )
    sm.add_event_handler(
        EventHandlerSpec(
            event_type="tick",
            handler_dialog_id="timer_handler",
            interrupt_level=InterruptLevel.BETWEEN_DIALOGS,
            resume_policy=ResumePolicy.DISCARD,
        )
    )
    sm.add_event_source(
        TimerSource(
            "tick",
            delay_seconds=0.02,
            repeat=False,
            interrupt_level=InterruptLevel.BETWEEN_DIALOGS,
            handler_dialog_id="timer_handler",
        )
    )

    await sm.run_async()

    calls = [c.args[0] for c in agent.say.call_args_list]
    assert "First" in calls
    assert "Timer fired!" in calls
    assert "Second" in calls

    # Handler must appear after first dialog and before second dialog.
    assert calls.index("Timer fired!") > calls.index("First")
    assert calls.index("Timer fired!") < calls.index("Second")


# ---------------------------------------------------------------------------
# Scenario 2 — BackgroundLLMSource fires BETWEEN_MOVES + PAUSE resume
# ---------------------------------------------------------------------------

_LLM_DIALOGS = [
    {
        "id": "two_moves",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [
            {"type": "say", "text": "Move 1"},
            {"type": "say", "text": "Move 2"},
        ],
    },
    {
        "id": "llm_handler",
        "type": "functional",
        "functional_type": "farewell",
        "moves": [{"type": "say", "text": "LLM result!"}],
    },
]


@pytest.fixture
def llm_dialogs_file(tmp_path):
    path = tmp_path / "llm_dialogs.json"
    path.write_text(json.dumps(_LLM_DIALOGS), encoding="utf-8")
    return str(path)


async def test_background_llm_injects_between_moves_with_pause_resume(llm_dialogs_file):
    """BackgroundLLMSource completes during Move 1 and the dialog resumes at Move 2.

    The LLM factory sleeps 20 ms before returning.  Move 1's say call sleeps
    50 ms so the LLM event arrives in the bus before _run_mini checks
    has_pending(BETWEEN_MOVES) ahead of Move 2.
    The PAUSE resume policy causes the handler dialog to run, then Move 2 continues.

    Expected say order: "Move 1" → "LLM result!" → "Move 2"
    """
    agent = _make_agent()

    async def slow_first_move(text):
        if text == "Move 1":
            await asyncio.sleep(0.05)

    agent.say.side_effect = slow_first_move

    sm = SessionManager(
        session_agenda=["two_moves"],
        agent=agent,
        dialog_json_path=llm_dialogs_file,
    )
    sm.add_event_handler(
        EventHandlerSpec(
            event_type="llm_ready",
            handler_dialog_id="llm_handler",
            interrupt_level=InterruptLevel.BETWEEN_MOVES,
            resume_policy=ResumePolicy.PAUSE,
        )
    )

    async def _fake_llm() -> str:
        await asyncio.sleep(0.02)
        return "some llm text"

    sm.add_event_source(
        BackgroundLLMSource(
            _fake_llm,
            event_type="llm_ready",
            interrupt_level=InterruptLevel.BETWEEN_MOVES,
            resume_policy=ResumePolicy.PAUSE,
            handler_dialog_id="llm_handler",
        )
    )

    await sm.run_async()

    calls = [c.args[0] for c in agent.say.call_args_list]
    assert "Move 1" in calls
    assert "LLM result!" in calls
    assert "Move 2" in calls

    # LLM handler must come between Move 1 and Move 2.
    assert calls.index("LLM result!") > calls.index("Move 1")
    assert calls.index("LLM result!") < calls.index("Move 2")


# ---------------------------------------------------------------------------
# Scenario 3 — wait_for_button resolved by a programmatic EventSource
# ---------------------------------------------------------------------------

_BUTTON_DIALOGS = [
    {
        "id": "button_dialog",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [
            {
                "type": "wait_for_button",
                "buttons": ["head_button"],
                "timeout": 5.0,
                "outcomes": {"head_button": "pressed"},
                "default_outcome": "timeout",
            },
            {
                "type": "branch",
                "on": "outcome",
                "cases": {
                    "pressed": [{"type": "say", "text": "Button pressed!"}],
                    "timeout":  [{"type": "say", "text": "Timed out."}],
                },
            },
        ],
    },
]


@pytest.fixture
def button_dialogs_file(tmp_path):
    path = tmp_path / "button_dialogs.json"
    path.write_text(json.dumps(_BUTTON_DIALOGS), encoding="utf-8")
    return str(path)


class _ButtonPressSource(EventSource):
    """Emits a single button_press event after a short delay.

    Used to simulate a physical button press in a deterministic unit test.
    """

    def __init__(self, button_id: str, delay: float = 0.02) -> None:
        self._button_id = button_id
        self._delay = delay

    @property
    def source_id(self) -> str:
        return self._button_id

    async def run(self, bus) -> None:
        await asyncio.sleep(self._delay)
        event = Event(
            priority=20,
            type="button_press",
            source=self._button_id,
            data={"button": self._button_id},
            interrupt_level=InterruptLevel.BETWEEN_MOVES,
            resume_policy=ResumePolicy.DISCARD,
        )
        await bus.emit(event)


async def test_wait_for_button_resolves_correct_outcome(button_dialogs_file):
    """A programmatic button press resolves wait_for_button to the correct outcome.

    The custom _ButtonPressSource emits after 20 ms.  The wait_for_button move
    subscribes to the bus and receives the event via the subscription fan-out
    (move-level delivery, not the session-level queue), setting
    ``current_outcome = "pressed"``.  The branch move then takes the "pressed"
    case and speaks "Button pressed!".
    """
    agent = _make_agent()

    sm = SessionManager(
        session_agenda=["button_dialog"],
        agent=agent,
        dialog_json_path=button_dialogs_file,
    )
    sm.add_event_source(_ButtonPressSource("head_button", delay=0.02))

    await sm.run_async()

    calls = [c.args[0] for c in agent.say.call_args_list]
    assert "Button pressed!" in calls
    assert "Timed out." not in calls


async def test_wait_for_button_timeout_falls_back_to_default_outcome(button_dialogs_file):
    """No button press within the timeout falls back to the default_outcome.

    This test uses a dialog with a very short timeout (50 ms) and no source
    that emits button events, so the wait expires and the "timeout" branch runs.
    """
    timeout_dialogs = [
        {
            "id": "button_dialog",
            "type": "functional",
            "functional_type": "greeting",
            "moves": [
                {
                    "type": "wait_for_button",
                    "buttons": ["head_button"],
                    "timeout": 0.05,
                    "outcomes": {"head_button": "pressed"},
                    "default_outcome": "timeout",
                },
                {
                    "type": "branch",
                    "on": "outcome",
                    "cases": {
                        "pressed": [{"type": "say", "text": "Button pressed!"}],
                        "timeout":  [{"type": "say", "text": "Timed out."}],
                    },
                },
            ],
        },
    ]

    import tempfile
    import os
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(timeout_dialogs, f)
        dialogs_path = f.name

    try:
        agent = _make_agent()
        sm = SessionManager(
            session_agenda=["button_dialog"],
            agent=agent,
            dialog_json_path=dialogs_path,
        )
        # No event source added — button is never pressed.
        await sm.run_async()
    finally:
        os.unlink(dialogs_path)

    calls = [c.args[0] for c in agent.say.call_args_list]
    assert "Timed out." in calls
    assert "Button pressed!" not in calls


# ---------------------------------------------------------------------------
# Scenario: full 3-dialog session with all three event types combined
# ---------------------------------------------------------------------------

_COMBINED_DIALOGS = [
    {
        "id": "greeting",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [{"type": "say", "text": "Hello!"}],
    },
    {
        "id": "interaction",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [
            {"type": "say", "text": "Interaction Move 1"},
            {"type": "say", "text": "Interaction Move 2"},
        ],
    },
    {
        "id": "farewell",
        "type": "functional",
        "functional_type": "farewell",
        "moves": [{"type": "say", "text": "Goodbye!"}],
    },
    {
        "id": "timer_handler",
        "type": "functional",
        "functional_type": "farewell",
        "moves": [{"type": "say", "text": "Checked in!"}],
    },
    {
        "id": "llm_inject_handler",
        "type": "functional",
        "functional_type": "farewell",
        "moves": [{"type": "say", "text": "Background result!"}],
    },
]


@pytest.fixture
def combined_dialogs_file(tmp_path):
    path = tmp_path / "combined.json"
    path.write_text(json.dumps(_COMBINED_DIALOGS), encoding="utf-8")
    return str(path)


async def test_combined_full_session(combined_dialogs_file):
    """3-dialog session with timer (BETWEEN_DIALOGS) + BETWEEN_MOVES + PAUSE resume.

    Agenda: greeting → interaction → farewell

    Events:
    - TimerSource fires at 20 ms.  greeting's say sleeps 50 ms so the timer
      event is guaranteed to be queued before the BETWEEN_DIALOGS drain ahead
      of interaction.
    - A BETWEEN_MOVES event for the LLM handler is injected deterministically
      from inside the "Interaction Move 1" say call (the same pattern used in
      the Phase 8 unit tests).  This ensures the event is in the queue exactly
      when _run_mini checks has_pending(BETWEEN_MOVES) before Move 2.

    Verified ordering:
      Hello! → Checked in! → Interaction Move 1 → Background result!
              → Interaction Move 2 → Goodbye!
    """
    agent = _make_agent()

    llm_injected = False

    async def timed_say(text):
        nonlocal llm_injected
        if text == "Hello!":
            # Sleep long enough for the 20 ms timer to fire.
            await asyncio.sleep(0.05)
        elif text == "Interaction Move 1" and not llm_injected:
            # Inject the BETWEEN_MOVES event deterministically while Move 1 is
            # in progress so it is available for the check before Move 2.
            llm_injected = True
            await sm._bus.emit(
                Event(
                    priority=40,
                    type="bg_llm",
                    source="test_injector",
                    interrupt_level=InterruptLevel.BETWEEN_MOVES,
                    resume_policy=ResumePolicy.PAUSE,
                    handler_dialog_id="llm_inject_handler",
                )
            )

    agent.say.side_effect = timed_say

    sm = SessionManager(
        session_agenda=["greeting", "interaction", "farewell"],
        agent=agent,
        dialog_json_path=combined_dialogs_file,
    )

    # Timer fires BETWEEN_DIALOGS before interaction.
    sm.add_event_handler(
        EventHandlerSpec(
            event_type="check_in",
            handler_dialog_id="timer_handler",
            interrupt_level=InterruptLevel.BETWEEN_DIALOGS,
            resume_policy=ResumePolicy.DISCARD,
        )
    )
    sm.add_event_source(
        TimerSource(
            "check_in",
            delay_seconds=0.02,
            repeat=False,
            interrupt_level=InterruptLevel.BETWEEN_DIALOGS,
            handler_dialog_id="timer_handler",
        )
    )

    # Register the LLM-inject handler so _run_handler_dialog can find it.
    # (The injected event carries handler_dialog_id directly, so the registry
    # entry is not strictly needed here — but it mirrors real session-plan usage.)
    sm.add_event_handler(
        EventHandlerSpec(
            event_type="bg_llm",
            handler_dialog_id="llm_inject_handler",
            interrupt_level=InterruptLevel.BETWEEN_MOVES,
            resume_policy=ResumePolicy.PAUSE,
        )
    )

    await sm.run_async()

    calls = [c.args[0] for c in agent.say.call_args_list]

    assert "Hello!" in calls
    assert "Checked in!" in calls
    assert "Interaction Move 1" in calls
    assert "Background result!" in calls
    assert "Interaction Move 2" in calls
    assert "Goodbye!" in calls

    # Check-in handler must appear after greeting and before interaction.
    assert calls.index("Checked in!") > calls.index("Hello!")
    assert calls.index("Checked in!") < calls.index("Interaction Move 1")

    # LLM handler must appear between the two interaction moves.
    assert calls.index("Background result!") > calls.index("Interaction Move 1")
    assert calls.index("Background result!") < calls.index("Interaction Move 2")

    # Farewell must be the final spoken utterance.
    assert calls[-1] == "Goodbye!"

    # All three main dialogs must be recorded as completed.
    assert "interaction" in sm.conversation_state.completed_dialogs
    assert "greeting" in sm.conversation_state.completed_dialogs
    assert "farewell" in sm.conversation_state.completed_dialogs
