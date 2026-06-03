import pytest

from nardial.events import Event, EventBus, InterruptLevel


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
