import asyncio

import pytest

from nardial.events import (
    EVENT_INTERACTION_PAUSE,
    EVENT_INTERACTION_RESUME,
    Event,
    EventBus,
    InterruptLevel,
)


@pytest.mark.asyncio
async def test_subscription_consumes_event_instead_of_queueing():
    bus = EventBus()
    queue = bus.subscribe(lambda ev: ev.type == "web_input")

    await bus.emit(
        Event(
            priority=10,
            type="web_input",
            source="screen",
            data={"value": "yes"},
            interrupt_level=InterruptLevel.BETWEEN_MOVES,
        )
    )

    received = await queue.get()
    assert received.data["value"] == "yes"
    assert not bus.has_pending(InterruptLevel.BETWEEN_MOVES)


@pytest.mark.asyncio
async def test_get_immediate_returns_best_priority_event():
    bus = EventBus()
    await bus.emit(
        Event(priority=50, type="a", source="s", interrupt_level=InterruptLevel.IMMEDIATE)
    )
    await bus.emit(
        Event(priority=10, type="b", source="s", interrupt_level=InterruptLevel.IMMEDIATE)
    )

    event = await bus.get_immediate()
    assert event is not None
    assert event.type == "b"
    assert bus.has_pending(InterruptLevel.IMMEDIATE)


@pytest.mark.asyncio
async def test_drain_at_level_does_not_remove_other_levels():
    bus = EventBus()
    await bus.emit(
        Event(priority=10, type="immediate", source="s", interrupt_level=InterruptLevel.IMMEDIATE)
    )
    await bus.emit(
        Event(
            priority=20,
            type="between_dialogs",
            source="s",
            interrupt_level=InterruptLevel.BETWEEN_DIALOGS,
        )
    )

    drained = await bus.drain_at_level(InterruptLevel.IMMEDIATE)
    assert [ev.type for ev in drained] == ["immediate"]
    assert not bus.has_pending(InterruptLevel.IMMEDIATE)
    assert bus.has_pending(InterruptLevel.BETWEEN_DIALOGS)


@pytest.mark.asyncio
async def test_pause_resume_events_control_blocking_state_without_queueing():
    bus = EventBus()

    await bus.emit(
        Event(priority=0, type=EVENT_INTERACTION_PAUSE, source="test")
    )

    assert bus.is_paused
    assert not bus.has_pending(InterruptLevel.BETWEEN_DIALOGS)

    waiter = asyncio.create_task(bus.wait_until_resumed())
    await asyncio.sleep(0)
    assert not waiter.done()

    await bus.emit(
        Event(priority=0, type=EVENT_INTERACTION_RESUME, source="test")
    )

    await asyncio.wait_for(waiter, timeout=1)
    assert not bus.is_paused


@pytest.mark.asyncio
async def test_shutdown_releases_paused_waiters():
    bus = EventBus()
    bus.pause()

    waiter = asyncio.create_task(bus.wait_until_resumed())
    await asyncio.sleep(0)
    assert not waiter.done()

    bus.shutdown()

    await asyncio.wait_for(waiter, timeout=1)
    assert not bus.is_paused
