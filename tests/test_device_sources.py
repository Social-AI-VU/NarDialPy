"""Phase 10 tests — device-specific EventSource implementations.

Verifies:
- PepperButtonSource: press (value=1) emits event; release (value=0) is ignored.
- PepperButtonSource: correct source identifier for each connector.
- PepperButtonSource: CancelledError propagates cleanly.
- NaoButtonSource: pressed buttons emit events with friendly identifiers.
- NaoButtonSource: released buttons (bool=False) are ignored.
- NaoButtonSource: unknown NAOqi key names pass through verbatim.
- NaoButtonSource: multiple buttons in one message each emit their own event.
- NaoButtonSource: CancelledError propagates cleanly.
- AlphaMiniButtonSource: exits immediately without emitting any events.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from nardial.events.bus import EventBus
from nardial.events.types import InterruptLevel, ResumePolicy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus():
    bus = EventBus()
    bus.set_loop(asyncio.get_running_loop())
    return bus


def _make_pepper_device():
    """Return a mock Pepper device with four sensor connectors."""
    device = MagicMock()
    for attr in ("tactile_sensor", "left_bumper", "right_bumper", "back_bumper"):
        connector = MagicMock()
        connector.register_callback = MagicMock()
        setattr(device, attr, connector)
    return device


def _make_nao_device():
    """Return a mock Nao device with a buttons connector."""
    device = MagicMock()
    device.buttons = MagicMock()
    device.buttons.register_callback = MagicMock()
    return device


def _make_msg(value):
    """Minimal SIC message stub with a value attribute."""
    msg = MagicMock()
    msg.value = value
    return msg


# ---------------------------------------------------------------------------
# PepperButtonSource
# ---------------------------------------------------------------------------

async def test_pepper_press_emits_event():
    """A press (value=1) on the tactile sensor should emit a button_press event."""
    from nardial.providers.device.pepper import PepperButtonSource

    device = _make_pepper_device()
    source = PepperButtonSource(device)
    bus = _make_bus()

    emitted = []
    original_emit = bus.emit

    async def capture_emit(event):
        emitted.append(event)
        await original_emit(event)

    bus.emit = capture_emit

    task = asyncio.create_task(source.run(bus))
    await asyncio.sleep(0)  # let run() set up loop/queue and register callbacks

    # Fire a 'press' callback for the tactile sensor.
    cb = device.tactile_sensor.register_callback.call_args[0][0]
    cb(_make_msg(value=1))

    await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert len(emitted) == 1
    assert emitted[0].type == "button_press"
    assert emitted[0].source == "head_tactile"


async def test_pepper_release_does_not_emit():
    """A release (value=0) must not emit any event."""
    from nardial.providers.device.pepper import PepperButtonSource

    device = _make_pepper_device()
    source = PepperButtonSource(device)
    bus = _make_bus()

    emitted = []
    original_emit = bus.emit

    async def capture_emit(event):
        emitted.append(event)
        await original_emit(event)

    bus.emit = capture_emit

    task = asyncio.create_task(source.run(bus))
    await asyncio.sleep(0)

    cb = device.tactile_sensor.register_callback.call_args[0][0]
    cb(_make_msg(value=0))

    await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert emitted == []


async def test_pepper_button_source_identifiers():
    """Each connector maps to the correct source identifier."""
    from nardial.providers.device.pepper import PepperButtonSource

    device = _make_pepper_device()
    source = PepperButtonSource(device)
    bus = _make_bus()

    emitted = []
    original_emit = bus.emit

    async def capture_emit(event):
        emitted.append(event)
        await original_emit(event)

    bus.emit = capture_emit

    task = asyncio.create_task(source.run(bus))
    await asyncio.sleep(0)

    expected = {
        "tactile_sensor": "head_tactile",
        "left_bumper":    "left_bumper",
        "right_bumper":   "right_bumper",
        "back_bumper":    "back_bumper",
    }

    for attr, expected_source in expected.items():
        connector = getattr(device, attr)
        cb = connector.register_callback.call_args[0][0]
        cb(_make_msg(value=1))

    await asyncio.sleep(0.02)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    sources = [e.source for e in emitted]
    for expected_source in expected.values():
        assert expected_source in sources


async def test_pepper_cancelled_error_propagates():
    """CancelledError from outside must not be swallowed."""
    from nardial.providers.device.pepper import PepperButtonSource

    device = _make_pepper_device()
    source = PepperButtonSource(device)
    bus = _make_bus()

    task = asyncio.create_task(source.run(bus))
    await asyncio.sleep(0)
    task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)


async def test_pepper_registers_all_callbacks():
    """All four connectors must have a callback registered."""
    from nardial.providers.device.pepper import PepperButtonSource

    device = _make_pepper_device()
    source = PepperButtonSource(device)
    bus = _make_bus()

    task = asyncio.create_task(source.run(bus))
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    for attr in ("tactile_sensor", "left_bumper", "right_bumper", "back_bumper"):
        connector = getattr(device, attr)
        connector.register_callback.assert_called_once()


# ---------------------------------------------------------------------------
# NaoButtonSource
# ---------------------------------------------------------------------------

async def test_nao_pressed_button_emits_event():
    """A pressed button (bool=True) emits a button_press event with friendly name."""
    from nardial.providers.device.nao import NaoButtonSource

    device = _make_nao_device()
    source = NaoButtonSource(device)
    bus = _make_bus()

    emitted = []
    original_emit = bus.emit

    async def capture_emit(event):
        emitted.append(event)
        await original_emit(event)

    bus.emit = capture_emit

    task = asyncio.create_task(source.run(bus))
    await asyncio.sleep(0)

    cb = device.buttons.register_callback.call_args[0][0]
    cb(_make_msg(value=[["ChestBoard/Button", True]]))

    await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert len(emitted) == 1
    assert emitted[0].source == "chest_button"
    assert emitted[0].data["naoqi_key"] == "ChestBoard/Button"


async def test_nao_released_button_ignored():
    """A release (bool=False) must not emit any event."""
    from nardial.providers.device.nao import NaoButtonSource

    device = _make_nao_device()
    source = NaoButtonSource(device)
    bus = _make_bus()

    emitted = []
    original_emit = bus.emit

    async def capture_emit(event):
        emitted.append(event)
        await original_emit(event)

    bus.emit = capture_emit

    task = asyncio.create_task(source.run(bus))
    await asyncio.sleep(0)

    cb = device.buttons.register_callback.call_args[0][0]
    cb(_make_msg(value=[["ChestBoard/Button", False]]))

    await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert emitted == []


async def test_nao_unknown_key_passes_through():
    """An unknown NAOqi key name is used verbatim as the source identifier."""
    from nardial.providers.device.nao import NaoButtonSource

    device = _make_nao_device()
    source = NaoButtonSource(device)
    bus = _make_bus()

    emitted = []
    original_emit = bus.emit

    async def capture_emit(event):
        emitted.append(event)
        await original_emit(event)

    bus.emit = capture_emit

    task = asyncio.create_task(source.run(bus))
    await asyncio.sleep(0)

    cb = device.buttons.register_callback.call_args[0][0]
    cb(_make_msg(value=[["FutureHardware/Button", True]]))

    await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert len(emitted) == 1
    assert emitted[0].source == "FutureHardware/Button"


async def test_nao_multiple_buttons_in_one_message():
    """Multiple pressed buttons in one message each emit a separate event."""
    from nardial.providers.device.nao import NaoButtonSource

    device = _make_nao_device()
    source = NaoButtonSource(device)
    bus = _make_bus()

    emitted = []
    original_emit = bus.emit

    async def capture_emit(event):
        emitted.append(event)
        await original_emit(event)

    bus.emit = capture_emit

    task = asyncio.create_task(source.run(bus))
    await asyncio.sleep(0)

    cb = device.buttons.register_callback.call_args[0][0]
    cb(_make_msg(value=[
        ["ChestBoard/Button", True],
        ["Head/Touch/Middle", True],
        ["LFoot/Bumper/Left", False],  # released — should not emit
    ]))

    await asyncio.sleep(0.02)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    sources = {e.source for e in emitted}
    assert "chest_button" in sources
    assert "head_middle" in sources
    assert len(emitted) == 2


async def test_nao_cancelled_error_propagates():
    """CancelledError from outside must not be swallowed."""
    from nardial.providers.device.nao import NaoButtonSource

    device = _make_nao_device()
    source = NaoButtonSource(device)
    bus = _make_bus()

    task = asyncio.create_task(source.run(bus))
    await asyncio.sleep(0)
    task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)


# ---------------------------------------------------------------------------
# AlphaMiniButtonSource
# ---------------------------------------------------------------------------

async def test_alphamini_source_exits_immediately():
    """AlphaMiniButtonSource.run() must return immediately and emit no events."""
    from nardial.providers.device.alphamini import AlphaMiniButtonSource

    source = AlphaMiniButtonSource()
    bus = _make_bus()

    emitted = []
    original_emit = bus.emit

    async def capture_emit(event):
        emitted.append(event)
        await original_emit(event)

    bus.emit = capture_emit

    # run() should complete on its own (no cancel needed).
    await asyncio.wait_for(source.run(bus), timeout=1.0)

    assert emitted == []


async def test_alphamini_adapter_returns_empty_sources():
    """AlphaminiAdapter.get_event_sources() returns an empty list."""
    from unittest.mock import MagicMock
    # Import lazily to avoid sic_framework import errors in unit-test environment.
    try:
        from nardial.providers.device.alphamini import AlphaminiAdapter
        device = MagicMock()
        adapter = AlphaminiAdapter(device)
        assert adapter.get_event_sources() == []
    except ImportError:
        pytest.skip("sic_framework or mini not available in test environment")
