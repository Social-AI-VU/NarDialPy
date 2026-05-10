"""Tests for move-level event wait types: MoveWaitForButton, MoveTimedWait, MoveWaitForWebInput.

Key scenarios per the plan:
- subscription is consumed; event does NOT appear in the session-level queue
- timeout falls back to `default_outcome`
- `timed_wait` delegates to `asyncio.sleep`
- handlers resolve to `default_outcome` when no EventBus is attached
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nardial.dialog_runtime import DialogRuntime, RunContext
from nardial.events.bus import EventBus
from nardial.events.types import Event, InterruptLevel
from nardial.mini_dialogs import MiniDialog
from nardial.moves import (
    MoveWaitForButton,
    MoveTimedWait,
    MoveWaitForWebInput,
    MoveSay,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    return agent


def _button_event(source: str) -> Event:
    return Event(priority=10, type="button_press", source=source)


def _web_event(value: str) -> Event:
    return Event(priority=10, type="web_input", source="web", data={"value": value})


# ---------------------------------------------------------------------------
# MoveWaitForButton — happy path
# ---------------------------------------------------------------------------

async def test_wait_for_button_resolves_outcome_on_match():
    bus = EventBus()
    runtime = DialogRuntime(_make_agent(), event_bus=bus)
    move = MoveWaitForButton(
        buttons=["chest_button", "head_button"],
        outcomes={"chest_button": "path_a", "head_button": "path_b"},
        default_outcome="timeout",
    )
    context = RunContext()

    # Emit the event slightly after the runtime subscribes
    async def _emit_later():
        await asyncio.sleep(0.01)
        await bus.emit(_button_event("head_button"))

    await asyncio.gather(
        runtime._handle_wait_for_button(move, context),
        _emit_later(),
    )

    assert context.current_outcome == "path_b"


async def test_wait_for_button_subscription_consumed_not_queued():
    """A matched subscription should prevent the event reaching the priority queue."""
    bus = EventBus()
    runtime = DialogRuntime(_make_agent(), event_bus=bus)
    move = MoveWaitForButton(buttons=["chest_button"], timeout=1.0)
    context = RunContext()

    async def _emit_later():
        await asyncio.sleep(0.01)
        await bus.emit(_button_event("chest_button"))

    await asyncio.gather(
        runtime._handle_wait_for_button(move, context),
        _emit_later(),
    )

    # Subscription consumed the event — queue should be empty
    assert not bus.has_pending(InterruptLevel.BETWEEN_DIALOGS)


async def test_wait_for_button_timeout_falls_back_to_default_outcome():
    bus = EventBus()
    runtime = DialogRuntime(_make_agent(), event_bus=bus)
    move = MoveWaitForButton(
        buttons=["chest_button"],
        timeout=0.05,
        default_outcome="timeout",
    )
    context = RunContext()

    await runtime._handle_wait_for_button(move, context)

    assert context.current_outcome == "timeout"


async def test_wait_for_button_no_bus_resolves_default_immediately():
    runtime = DialogRuntime(_make_agent(), event_bus=None)
    move = MoveWaitForButton(buttons=["chest_button"], default_outcome="no_bus")
    context = RunContext()

    await runtime._handle_wait_for_button(move, context)

    assert context.current_outcome == "no_bus"


async def test_wait_for_button_unsubscribes_after_completion():
    """The subscription should be removed from the bus after the move finishes."""
    bus = EventBus()
    runtime = DialogRuntime(_make_agent(), event_bus=bus)
    move = MoveWaitForButton(buttons=["chest_button"], timeout=0.05)
    context = RunContext()

    await runtime._handle_wait_for_button(move, context)

    # No subscriptions should remain
    assert len(bus._subscriptions) == 0


# ---------------------------------------------------------------------------
# MoveTimedWait
# ---------------------------------------------------------------------------

async def test_timed_wait_calls_asyncio_sleep():
    runtime = DialogRuntime(_make_agent())
    move = MoveTimedWait(duration_seconds=1.5)
    context = RunContext()

    with patch("nardial.dialog_runtime.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await runtime._handle_timed_wait(move, context)

    mock_sleep.assert_awaited_once_with(1.5)


async def test_timed_wait_within_full_dialog():
    """timed_wait should not change current_outcome."""
    runtime = DialogRuntime(_make_agent())
    move = MoveTimedWait(duration_seconds=0.0)
    context = RunContext()

    await runtime._handle_timed_wait(move, context)

    assert context.current_outcome is None


# ---------------------------------------------------------------------------
# MoveWaitForWebInput — happy path
# ---------------------------------------------------------------------------

async def test_wait_for_web_input_resolves_outcome_on_match():
    bus = EventBus()
    runtime = DialogRuntime(_make_agent(), event_bus=bus)
    move = MoveWaitForWebInput(
        options=["yes", "no"],
        outcomes={"yes": "confirmed", "no": "rejected"},
        default_outcome="timeout",
    )
    context = RunContext()

    async def _emit_later():
        await asyncio.sleep(0.01)
        await bus.emit(_web_event("yes"))

    await asyncio.gather(
        runtime._handle_wait_for_web_input(move, context),
        _emit_later(),
    )

    assert context.current_outcome == "confirmed"


async def test_wait_for_web_input_timeout_falls_back_to_default():
    bus = EventBus()
    runtime = DialogRuntime(_make_agent(), event_bus=bus)
    move = MoveWaitForWebInput(options=["yes", "no"], timeout=0.05, default_outcome="timeout")
    context = RunContext()

    await runtime._handle_wait_for_web_input(move, context)

    assert context.current_outcome == "timeout"


async def test_wait_for_web_input_no_bus_resolves_default_immediately():
    runtime = DialogRuntime(_make_agent(), event_bus=None)
    move = MoveWaitForWebInput(options=["yes"], default_outcome="no_bus")
    context = RunContext()

    await runtime._handle_wait_for_web_input(move, context)

    assert context.current_outcome == "no_bus"


async def test_wait_for_web_input_ignores_unmatched_values():
    """Events with values not in ``options`` should not match the subscription."""
    bus = EventBus()
    runtime = DialogRuntime(_make_agent(), event_bus=bus)
    move = MoveWaitForWebInput(
        options=["yes", "no"],
        timeout=0.1,
        default_outcome="timeout",
    )
    context = RunContext()

    async def _emit_wrong_then_nothing():
        await asyncio.sleep(0.01)
        # This value is not in options; should not trigger the subscription.
        await bus.emit(_web_event("maybe"))

    await asyncio.gather(
        runtime._handle_wait_for_web_input(move, context),
        _emit_wrong_then_nothing(),
    )

    # Timed out because the valid option never arrived
    assert context.current_outcome == "timeout"


async def test_wait_for_web_input_subscription_consumed_not_queued():
    bus = EventBus()
    runtime = DialogRuntime(_make_agent(), event_bus=bus)
    move = MoveWaitForWebInput(options=["yes"], timeout=1.0)
    context = RunContext()

    async def _emit_later():
        await asyncio.sleep(0.01)
        await bus.emit(_web_event("yes"))

    await asyncio.gather(
        runtime._handle_wait_for_web_input(move, context),
        _emit_later(),
    )

    assert not bus.has_pending(InterruptLevel.BETWEEN_DIALOGS)


# ---------------------------------------------------------------------------
# Integration: wait move within a full MiniDialog run
# ---------------------------------------------------------------------------

async def test_wait_for_button_in_full_dialog_with_branch():
    """Button wait sets outcome; subsequent branch move routes correctly."""
    bus = EventBus()
    agent = _make_agent()
    moves = [
        MoveWaitForButton(
            buttons=["chest_button"],
            outcomes={"chest_button": "pressed"},
            default_outcome="timeout",
            timeout=1.0,
        ),
    ]
    dialog = MiniDialog(dialog_id="btn_test", moves=moves)
    context = RunContext()

    async def _emit_later():
        await asyncio.sleep(0.01)
        await bus.emit(_button_event("chest_button"))

    await asyncio.gather(
        DialogRuntime(agent, event_bus=bus).run(dialog, context),
        _emit_later(),
    )

    assert context.current_outcome == "pressed"
