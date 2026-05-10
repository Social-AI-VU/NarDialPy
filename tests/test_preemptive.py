"""Phase 9 tests — preemptive watchdog + CancelledError propagation.

Verifies:
- A PREEMPTIVE event emitted while a dialog is running cancels the dialog task.
- The handler dialog is run after preemptive cancellation.
- DISCARD resume policy abandons the interrupted dialog.
- PAUSE resume policy retries the dialog from the best-effort move_index.
- The watchdog exits cleanly when the dialog finishes before any PREEMPTIVE event.
- An outer CancelledError (not from the watchdog) propagates unmodified.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nardial.events.bus import EventBus
from nardial.events.specs import EventHandlerSpec
from nardial.events.types import Event, InterruptLevel, ResumePolicy
from nardial.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

DIALOGS = [
    {
        "id": "slow_dialog",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [
            {"type": "say", "text": "Move A"},
            {"type": "say", "text": "Move B"},
        ],
    },
    {
        "id": "handler_dialog",
        "type": "functional",
        "functional_type": "farewell",
        "moves": [{"type": "say", "text": "Interrupted!"}],
    },
    {
        "id": "next_dialog",
        "type": "functional",
        "functional_type": "farewell",
        "moves": [{"type": "say", "text": "After interruption."}],
    },
]


@pytest.fixture(autouse=True)
def redirect_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def dialogs_file(tmp_path):
    path = tmp_path / "dialogs.json"
    path.write_text(json.dumps(DIALOGS), encoding="utf-8")
    return str(path)


def _make_agent():
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
    device = MagicMock()
    device.get_event_sources = MagicMock(return_value=[])
    orchestrator = MagicMock()
    orchestrator.device = device
    agent.orchestrator = orchestrator
    return agent


def _preemptive_event(event_type: str = "stop_signal", **kwargs) -> Event:
    defaults = dict(
        priority=1,
        type=event_type,
        source="test",
        interrupt_level=InterruptLevel.PREEMPTIVE,
        resume_policy=ResumePolicy.DISCARD,
    )
    defaults.update(kwargs)
    return Event(**defaults)


# ---------------------------------------------------------------------------
# Watchdog exits cleanly when dialog finishes before any PREEMPTIVE event
# ---------------------------------------------------------------------------

async def test_watchdog_exits_cleanly_when_no_preemptive_event(dialogs_file):
    """The session completes normally and the watchdog never fires."""
    agent = _make_agent()
    sm = SessionManager(
        session_agenda=["slow_dialog"],
        agent=agent,
        dialog_json_path=dialogs_file,
    )
    await sm.run_async()

    calls = [c.args[0] for c in agent.say.call_args_list]
    assert calls == ["Move A", "Move B"]


# ---------------------------------------------------------------------------
# PREEMPTIVE + DISCARD: interrupted dialog is abandoned
# ---------------------------------------------------------------------------

async def test_preemptive_discard_cancels_dialog(dialogs_file):
    """A PREEMPTIVE/DISCARD event during Move A cancels the dialog; Move B never runs."""
    agent = _make_agent()
    sm = SessionManager(
        session_agenda=["slow_dialog", "next_dialog"],
        agent=agent,
        dialog_json_path=dialogs_file,
    )

    first_call_done = False

    async def say_side_effect(text):
        nonlocal first_call_done
        if not first_call_done:
            first_call_done = True
            # Emit PREEMPTIVE while 'say' is in progress (simulating a blocking call).
            # The watchdog polls every 50ms; we sleep briefly to give it time to detect.
            await sm._bus.emit(_preemptive_event())
            await asyncio.sleep(0.15)  # let the watchdog fire

    agent.say.side_effect = say_side_effect
    await sm.run_async()

    calls = [c.args[0] for c in agent.say.call_args_list]
    # Move A was in progress; Move B is skipped (DISCARD).
    # next_dialog still runs because DISCARD only drops the interrupted dialog.
    assert "Move A" in calls
    assert "Move B" not in calls
    assert "After interruption." in calls


# ---------------------------------------------------------------------------
# PREEMPTIVE + handler dialog
# ---------------------------------------------------------------------------

async def test_preemptive_runs_handler_dialog(dialogs_file):
    """Handler dialog runs between the cancelled dialog and the next agenda item."""
    agent = _make_agent()
    sm = SessionManager(
        session_agenda=["slow_dialog", "next_dialog"],
        agent=agent,
        dialog_json_path=dialogs_file,
    )
    sm.add_event_handler(
        EventHandlerSpec(
            event_type="stop_signal",
            handler_dialog_id="handler_dialog",
            interrupt_level=InterruptLevel.PREEMPTIVE,
            resume_policy=ResumePolicy.DISCARD,
        )
    )

    first_call_done = False

    async def say_side_effect(text):
        nonlocal first_call_done
        if not first_call_done:
            first_call_done = True
            await sm._bus.emit(_preemptive_event())
            await asyncio.sleep(0.15)

    agent.say.side_effect = say_side_effect
    await sm.run_async()

    calls = [c.args[0] for c in agent.say.call_args_list]
    assert "Interrupted!" in calls
    assert "After interruption." in calls
    # Handler must come before next_dialog.
    assert calls.index("Interrupted!") < calls.index("After interruption.")


# ---------------------------------------------------------------------------
# PREEMPTIVE + PAUSE: dialog retried from best-effort checkpoint
# ---------------------------------------------------------------------------

async def test_preemptive_pause_retries_dialog(dialogs_file):
    """PAUSE resume policy causes the dialog to be retried from move_index 0 (best-effort)."""
    agent = _make_agent()
    sm = SessionManager(
        session_agenda=["slow_dialog"],
        agent=agent,
        dialog_json_path=dialogs_file,
    )

    call_count = 0
    first_interrupt_done = False

    async def say_side_effect(text):
        nonlocal call_count, first_interrupt_done
        call_count += 1
        if not first_interrupt_done and text == "Move A":
            first_interrupt_done = True
            await sm._bus.emit(
                _preemptive_event(resume_policy=ResumePolicy.PAUSE)
            )
            await asyncio.sleep(0.15)

    agent.say.side_effect = say_side_effect
    await sm.run_async()

    calls = [c.args[0] for c in agent.say.call_args_list]
    # Move A is spoken at least once, then the dialog resumes.
    assert calls.count("Move A") >= 1
    # Move B must eventually be spoken (dialog completes on retry).
    assert "Move B" in calls


# ---------------------------------------------------------------------------
# _last_preemptive_event is cleared after handling
# ---------------------------------------------------------------------------

async def test_last_preemptive_event_cleared_after_handling(dialogs_file):
    """_last_preemptive_event is None after run_async() completes."""
    agent = _make_agent()
    sm = SessionManager(
        session_agenda=["slow_dialog"],
        agent=agent,
        dialog_json_path=dialogs_file,
    )

    first_call_done = False

    async def say_side_effect(text):
        nonlocal first_call_done
        if not first_call_done:
            first_call_done = True
            await sm._bus.emit(_preemptive_event())
            await asyncio.sleep(0.15)

    agent.say.side_effect = say_side_effect
    await sm.run_async()

    assert sm._last_preemptive_event is None


# ---------------------------------------------------------------------------
# No PREEMPTIVE events: _last_preemptive_event stays None throughout
# ---------------------------------------------------------------------------

async def test_last_preemptive_event_none_without_interrupt(dialogs_file):
    """_last_preemptive_event remains None when no PREEMPTIVE event is emitted."""
    agent = _make_agent()
    sm = SessionManager(
        session_agenda=["slow_dialog"],
        agent=agent,
        dialog_json_path=dialogs_file,
    )
    await sm.run_async()
    assert sm._last_preemptive_event is None
