"""Tests for session-wide controls (pause/resume, skip_listen) and the keyboard source."""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nardial.controls import SessionControl
from nardial.events import Event, EventBus
from nardial.events.sources import KeyboardSource, key_name
from nardial.interaction_orchestrator import InteractionConfig, InteractionOrchestrator
from nardial.providers.nlu import NLUResult


def _key(value, event_type="keyboard"):
    return Event(priority=0, type=event_type, source="test", data={"value": value})


# ---------------------------------------------------------------------------
# Config / bindings
# ---------------------------------------------------------------------------

def test_string_triggers_are_keyboard_keys():
    control = SessionControl({"toggle_pause": ["Space"], "skip_listen": ["s"]})
    assert control.bindings == {("keyboard", "space"): "toggle_pause", ("keyboard", "s"): "skip_listen"}
    assert isinstance(control.sources[0], KeyboardSource)


def test_dict_triggers_bind_other_event_types():
    control = SessionControl({"toggle_pause": [{"robot_button": "head_front"}]})
    assert control.action_for(_key("head_front", "robot_button")) == "toggle_pause"
    assert control.sources == []  # no keyboard trigger, so no keyboard listener


def test_unknown_control_raises():
    with pytest.raises(ValueError):
        SessionControl({"toggle_paws": ["space"]})


def test_start_paused():
    assert SessionControl({"start_paused": True, "toggle_pause": ["space"]}).paused
    assert not SessionControl({"toggle_pause": ["space"]}).paused


def test_handle_toggles_pause_and_ignores_unbound_keys():
    control = SessionControl({"toggle_pause": ["space"]})
    control.handle(_key("x"))
    assert not control.paused
    control.handle(_key("space"))
    assert control.paused
    control.handle(_key("space"))
    assert not control.paused


async def test_bus_events_reach_control():
    bus = EventBus()
    control = SessionControl({"toggle_pause": ["space"]})
    control.sources = []  # don't start a real keyboard listener
    await control.start(bus)
    try:
        await bus.emit(_key("space"))
        await asyncio.sleep(0)
        assert control.paused
    finally:
        await control.stop()


# ---------------------------------------------------------------------------
# SessionControl.run
# ---------------------------------------------------------------------------

async def test_run_returns_result_when_not_interrupted():
    control = SessionControl({"toggle_pause": ["space"]})

    async def work():
        return 42

    assert await control.run(work) == 42


async def test_pause_restarts_work_after_resume():
    control = SessionControl({"toggle_pause": ["space"]})
    calls = []
    started = asyncio.Event()

    async def work():
        calls.append(1)
        started.set()
        if len(calls) == 1:
            await asyncio.sleep(10)  # interrupted by the pause
        return "done"

    runner = asyncio.create_task(control.run(work))
    await started.wait()
    control.pause()
    await asyncio.sleep(0.01)
    assert not runner.done()
    control.resume()
    assert await asyncio.wait_for(runner, 1) == "done"
    assert len(calls) == 2


async def test_start_paused_blocks_until_resume():
    control = SessionControl({"start_paused": True, "toggle_pause": ["space"]})

    async def work():
        return "started"

    runner = asyncio.create_task(control.run(work))
    await asyncio.sleep(0.01)
    assert not runner.done()
    control.resume()
    assert await asyncio.wait_for(runner, 1) == "started"


async def test_pause_during_listen_keeps_the_result_until_resume():
    control = SessionControl({"toggle_pause": ["space"]})
    stop = asyncio.Event()
    calls = []

    async def work():
        calls.append(1)
        await stop.wait()  # like a listen that only returns once it is told to stop
        return "half a sentence"

    runner = asyncio.create_task(control.run(work, on_stop=stop.set))
    await asyncio.sleep(0.01)
    control.pause()
    await asyncio.sleep(0.01)
    assert not runner.done()  # held while paused
    control.resume()
    assert await asyncio.wait_for(runner, 1) == "half a sentence"
    assert len(calls) == 1  # not listened again


async def test_skip_calls_on_stop_and_keeps_the_result():
    control = SessionControl({"skip_listen": ["s"]})
    stop = asyncio.Event()

    async def work():
        await stop.wait()  # like a listen that only returns once it is told to stop
        return "half a sentence"

    runner = asyncio.create_task(control.run(work, on_stop=stop.set))
    await asyncio.sleep(0.01)
    control.skip_listen()
    assert await asyncio.wait_for(runner, 1) == "half a sentence"


async def test_skip_gives_up_after_grace_when_work_does_not_stop():
    control = SessionControl({"skip_listen": ["s"]})
    on_stop = Mock()

    async def work():
        await asyncio.sleep(10)  # a provider whose cancel() does nothing

    runner = asyncio.create_task(control.run(work, on_stop=on_stop, stop_grace=0.05))
    await asyncio.sleep(0.01)
    control.skip_listen()
    assert await asyncio.wait_for(runner, 1) is None
    on_stop.assert_called_once()


async def test_skip_before_run_is_ignored():
    control = SessionControl({"skip_listen": ["s"]})
    control.skip_listen()  # pressed while nothing was listening
    on_stop = Mock()

    async def work():
        return "heard"

    assert await control.run(work, on_stop=on_stop) == "heard"
    on_stop.assert_not_called()


# ---------------------------------------------------------------------------
# Orchestrator integration
# ---------------------------------------------------------------------------

def _make_orchestrator(controls=None):
    # Skip __init__, which sets up logging and SIC services.
    orch = object.__new__(InteractionOrchestrator)
    orch.set_interaction_conf(InteractionConfig(signal_listening_behavior=False, controls=controls))
    if orch.control is not None:
        orch.control.sources = []  # don't start a real keyboard listener
    orch.nlu_provider = Mock()
    orch.screen_provider = None
    orch._log_queue = None
    return orch


def test_interaction_config_controls_build_session_control():
    assert _make_orchestrator().control is None
    orch = _make_orchestrator({"toggle_pause": ["space"]})
    assert orch.control.action_for(_key("space")) == "toggle_pause"


async def test_controls_start_on_first_listen_without_session_manager():
    orch = _make_orchestrator({"toggle_pause": ["space"]})
    orch.nlu_provider.listen.return_value = NLUResult(transcript="hoi")
    try:
        await orch.listen()
        assert orch.control.started
    finally:
        await orch.stop_controls()
    assert not orch.control.started


async def test_start_controls_moves_to_the_session_bus():
    orch = _make_orchestrator({"toggle_pause": ["space"]})
    await orch.start_controls()  # e.g. started lazily on its own bus
    session_bus = EventBus()
    try:
        await orch.start_controls(session_bus)
        await session_bus.emit(_key("space"))
        await asyncio.sleep(0)
        assert orch.control.paused
    finally:
        await orch.stop_controls()


async def test_skip_listen_stops_provider_and_keeps_what_was_heard():
    orch = _make_orchestrator({"skip_listen": ["s"]})
    stopped = threading.Event()
    # Like Dialogflow: listen() only returns the final transcript once it is told to stop.
    orch.nlu_provider.listen.side_effect = lambda **kw: stopped.wait(5) and NLUResult(transcript="een draak")
    orch.nlu_provider.cancel.side_effect = stopped.set

    try:
        runner = asyncio.create_task(orch.listen(timeout=5))
        await asyncio.sleep(0.05)
        orch.control.skip_listen()
        assert await asyncio.wait_for(runner, 1) == NLUResult(transcript="een draak", interrupted=True)
        orch.nlu_provider.cancel.assert_called_once()
    finally:
        stopped.set()
        await orch.stop_controls()


async def test_listen_without_control_is_unchanged():
    orch = _make_orchestrator()
    orch.nlu_provider.listen.return_value = NLUResult(transcript="hoi")
    result = await orch.listen()
    assert result.transcript == "hoi"
    assert not result.interrupted


# ---------------------------------------------------------------------------
# Keyboard source
# ---------------------------------------------------------------------------

def test_key_name():
    assert key_name(SimpleNamespace(char="A")) == "a"
    assert key_name(SimpleNamespace(char=None, name="space")) == "space"
    assert key_name(SimpleNamespace()) is None
