"""Phase 8 tests — SessionManager.run_async(), _dialog_loop(), event bus integration.

Verifies:
- run_async() creates an EventBus and passes it to DialogRuntime
- TimerSource fires BETWEEN_DIALOGS; handler dialog runs before the next dialog
- BETWEEN_MOVES event with PAUSE causes dialog to resume from checkpoint
- Source tasks are cancelled when the dialog loop ends
- _run_handler_dialog: missing dialog logs warning and does not crash
- _bus is initialized to None before run_async is called
"""

import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from nardial.conversation_state import ConversationState
from nardial.events.bus import EventBus
from nardial.events.specs import EventHandlerSpec
from nardial.events.types import Event, InterruptLevel, ResumePolicy
from nardial.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

SIMPLE_DIALOGS = [
    {
        "id": "greeting",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [{"type": "say", "text": "Hello!"}],
    },
    {
        "id": "farewell",
        "type": "functional",
        "functional_type": "farewell",
        "moves": [{"type": "say", "text": "Goodbye!"}],
    },
    {
        "id": "handler_dialog",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [{"type": "say", "text": "Interrupting!"}],
    },
]


@pytest.fixture(autouse=True)
def redirect_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def dialogs_file(tmp_path):
    path = tmp_path / "dialogs.json"
    path.write_text(json.dumps(SIMPLE_DIALOGS), encoding="utf-8")
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
    # device stub — returns no event sources
    device = MagicMock()
    device.get_event_sources = MagicMock(return_value=[])
    orchestrator = MagicMock()
    orchestrator.device = device
    agent.orchestrator = orchestrator
    return agent


def _make_event(event_type: str, **kwargs) -> Event:
    defaults = dict(
        priority=10,
        type=event_type,
        source="test",
        interrupt_level=InterruptLevel.BETWEEN_DIALOGS,
        resume_policy=ResumePolicy.DISCARD,
    )
    defaults.update(kwargs)
    return Event(**defaults)


# ---------------------------------------------------------------------------
# Basic run_async tests
# ---------------------------------------------------------------------------

async def test_run_async_completes_normally(dialogs_file):
    """run_async() should execute all agenda dialogs and return without error."""
    agent = _make_agent()
    sm = SessionManager(
        session_agenda=["greeting", "farewell"],
        agent=agent,
        dialog_json_path=dialogs_file,
    )
    await sm.run_async()

    assert agent.say.call_count == 2
    calls = [c.args[0] for c in agent.say.call_args_list]
    assert calls == ["Hello!", "Goodbye!"]


async def test_bus_is_none_before_run_async(dialogs_file):
    """_bus must be None before run_async() is called."""
    agent = _make_agent()
    sm = SessionManager(session_agenda=[], agent=agent, dialog_json_path=dialogs_file)
    assert sm._bus is None


async def test_run_async_creates_event_bus(dialogs_file):
    """run_async() must attach an EventBus to _bus."""
    captured_bus = []

    agent = _make_agent()

    async def _capture_bus(text):
        if not captured_bus:
            captured_bus.append(sm._bus)

    sm = SessionManager(
        session_agenda=["greeting"],
        agent=agent,
        dialog_json_path=dialogs_file,
    )
    agent.say.side_effect = _capture_bus
    await sm.run_async()

    assert len(captured_bus) == 1
    assert isinstance(captured_bus[0], EventBus)


async def test_run_async_shuts_down_bus_after_loop(dialogs_file):
    """EventBus.shutdown() must be called after the dialog loop completes."""
    agent = _make_agent()
    sm = SessionManager(session_agenda=[], agent=agent, dialog_json_path=dialogs_file)
    await sm.run_async()
    assert sm._bus._closed


async def test_run_async_source_tasks_are_cancelled_when_done(dialogs_file):
    """Source tasks must be cancelled when the dialog loop finishes.

    Uses asyncio.Event to confirm both startup and cancellation, which avoids
    the closure-capture race that plain-list approaches suffer from.
    """
    agent = _make_agent()
    sm = SessionManager(session_agenda=[], agent=agent, dialog_json_path=dialogs_file)

    task_started = asyncio.Event()
    task_cancelled = asyncio.Event()

    class _InfiniteSource:
        source_id = "infinite"

        async def run(self, bus):
            task_started.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                task_cancelled.set()
                raise

    sm.add_event_source(_InfiniteSource())
    await sm.run_async()

    # run_async() only returns after gather() finishes, which only finishes
    # after the source task's CancelledError has propagated (gather captures it).
    assert task_started.is_set(), "Source task should have started"
    assert task_cancelled.is_set(), "Source task should have been cancelled"


# ---------------------------------------------------------------------------
# BETWEEN_DIALOGS: event emitted inside first dialog, drained before second
# ---------------------------------------------------------------------------

async def test_between_dialogs_handler_runs_before_next_dialog(dialogs_file):
    """A BETWEEN_DIALOGS event queued during the first dialog triggers the handler
    dialog before the second main dialog starts.

    The event is emitted deterministically from inside the first say() call, so
    it is guaranteed to be in the bus queue when the dialog loop drains
    BETWEEN_DIALOGS events before starting the second dialog.
    """
    agent = _make_agent()
    sm = SessionManager(
        session_agenda=["greeting", "farewell"],
        agent=agent,
        dialog_json_path=dialogs_file,
    )
    sm.add_event_handler(
        EventHandlerSpec(
            event_type="check_in",
            handler_dialog_id="handler_dialog",
            interrupt_level=InterruptLevel.BETWEEN_DIALOGS,
            resume_policy=ResumePolicy.DISCARD,
        )
    )

    say_calls = []
    first_say_done = False

    async def say_side_effect(text):
        nonlocal first_say_done
        say_calls.append(text)
        if not first_say_done:
            first_say_done = True
            # Emit the BETWEEN_DIALOGS event while the first dialog is still running.
            # It will be drained synchronously by the dialog loop before farewell starts.
            await sm._bus.emit(
                _make_event(
                    "check_in",
                    handler_dialog_id="handler_dialog",
                    interrupt_level=InterruptLevel.BETWEEN_DIALOGS,
                )
            )

    agent.say.side_effect = say_side_effect
    await sm.run_async()

    # greeting → (handler emitted) → handler_dialog → farewell
    assert "Hello!" in say_calls
    assert "Interrupting!" in say_calls
    assert "Goodbye!" in say_calls
    # handler must come before farewell
    assert say_calls.index("Interrupting!") < say_calls.index("Goodbye!")


# ---------------------------------------------------------------------------
# BETWEEN_MOVES: event emitted inside first move, dialog pauses then resumes
# ---------------------------------------------------------------------------

async def test_between_moves_pause_resumes_dialog(tmp_path, redirect_cwd):
    """A BETWEEN_MOVES event with PAUSE should cause the dialog to resume from
    the interrupted move after the handler dialog runs.

    The event is emitted deterministically from inside the first say() call,
    guaranteeing it is in the queue when _run_mini checks has_pending before
    dispatching the second move.
    """
    two_move_dialogs = [
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
            "id": "handler_dialog",
            "type": "functional",
            "functional_type": "farewell",
            "moves": [{"type": "say", "text": "Handler!"}],
        },
    ]
    dialogs_file = str(tmp_path / "dialogs.json")
    with open(dialogs_file, "w", encoding="utf-8") as f:
        json.dump(two_move_dialogs, f)

    agent = _make_agent()
    sm = SessionManager(
        session_agenda=["two_moves"],
        agent=agent,
        dialog_json_path=dialogs_file,
    )
    sm.add_event_handler(
        EventHandlerSpec(
            event_type="pause_event",
            handler_dialog_id="handler_dialog",
            interrupt_level=InterruptLevel.BETWEEN_MOVES,
            resume_policy=ResumePolicy.PAUSE,
        )
    )

    say_calls = []
    first_move_done = False

    async def say_side_effect(text):
        nonlocal first_move_done
        say_calls.append(text)
        if not first_move_done:
            first_move_done = True
            # Emit while inside the first move; _run_mini will see it before
            # dispatching Move 2.
            await sm._bus.emit(
                _make_event(
                    "pause_event",
                    handler_dialog_id="handler_dialog",
                    interrupt_level=InterruptLevel.BETWEEN_MOVES,
                    resume_policy=ResumePolicy.PAUSE,
                )
            )

    agent.say.side_effect = say_side_effect
    await sm.run_async()

    # Move 1 → (interrupt) → Handler! → Move 2 (resumed from checkpoint at index=1)
    assert "Move 1" in say_calls
    assert "Handler!" in say_calls
    assert "Move 2" in say_calls
    assert say_calls[0] == "Move 1"
    assert say_calls.index("Handler!") < say_calls.index("Move 2")


# ---------------------------------------------------------------------------
# _run_handler_dialog: missing dialog is non-fatal
# ---------------------------------------------------------------------------

async def test_run_handler_dialog_missing_dialog_logs_warning(dialogs_file, caplog):
    """If the handler dialog ID is not in the registry, a warning is logged but no crash."""
    import logging
    agent = _make_agent()
    sm = SessionManager(session_agenda=[], agent=agent, dialog_json_path=dialogs_file)
    sm._bus = EventBus()
    sm._bus.set_loop(asyncio.get_running_loop())

    from nardial.dialog_runtime import DialogRuntime, RunContext

    runtime = DialogRuntime(agent, event_bus=sm._bus)
    run_context = RunContext()
    context = sm._build_agenda_context()

    ev = _make_event("ghost", handler_dialog_id="nonexistent_dialog")

    with caplog.at_level(logging.WARNING):
        await sm._run_handler_dialog(ev, runtime, run_context, context)

    assert any("nonexistent_dialog" in r.message for r in caplog.records)


async def test_run_handler_dialog_no_handler_configured_is_silent(dialogs_file, caplog):
    """An event with no handler_dialog_id and no registered handler is silently skipped."""
    import logging
    agent = _make_agent()
    sm = SessionManager(session_agenda=[], agent=agent, dialog_json_path=dialogs_file)
    sm._bus = EventBus()
    sm._bus.set_loop(asyncio.get_running_loop())

    from nardial.dialog_runtime import DialogRuntime, RunContext

    runtime = DialogRuntime(agent, event_bus=sm._bus)
    run_context = RunContext()
    context = sm._build_agenda_context()

    # Event with no handler and no registry entry
    ev = _make_event("unknown_event")  # no handler_dialog_id

    with caplog.at_level(logging.DEBUG):
        await sm._run_handler_dialog(ev, runtime, run_context, context)

    agent.say.assert_not_called()
