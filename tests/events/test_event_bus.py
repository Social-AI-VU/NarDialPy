"""Tests for EventBus — subscription fan-out, priority queue, and drain helpers."""

import asyncio
import pytest

from nardial.events import (
    Event,
    EventBus,
    InterruptLevel,
    ResumePolicy,
)


def _make_event(
    event_type: str = "test",
    priority: int = 50,
    interrupt_level: InterruptLevel = InterruptLevel.BETWEEN_DIALOGS,
    resume_policy: ResumePolicy = ResumePolicy.DISCARD,
    source: str = "test_source",
    handler_dialog_id: str | None = None,
    data=None,
) -> Event:
    return Event(
        priority=priority,
        type=event_type,
        source=source,
        interrupt_level=interrupt_level,
        resume_policy=resume_policy,
        handler_dialog_id=handler_dialog_id,
        data=data,
    )


# ---------------------------------------------------------------------------
# Session-level queue: emit + drain
# ---------------------------------------------------------------------------

async def test_emit_places_event_in_queue():
    bus = EventBus()
    ev = _make_event()
    await bus.emit(ev)
    assert bus.has_pending(InterruptLevel.BETWEEN_DIALOGS)


async def test_drain_at_level_returns_matching_events():
    bus = EventBus()
    ev1 = _make_event(event_type="a", interrupt_level=InterruptLevel.BETWEEN_DIALOGS)
    ev2 = _make_event(event_type="b", interrupt_level=InterruptLevel.BETWEEN_MOVES)
    ev3 = _make_event(event_type="c", interrupt_level=InterruptLevel.BETWEEN_DIALOGS)
    await bus.emit(ev1)
    await bus.emit(ev2)
    await bus.emit(ev3)

    drained = await bus.drain_at_level(InterruptLevel.BETWEEN_DIALOGS)
    assert len(drained) == 2
    assert all(e.interrupt_level == InterruptLevel.BETWEEN_DIALOGS for e in drained)

    # The BETWEEN_MOVES event should still be in the queue
    assert bus.has_pending(InterruptLevel.BETWEEN_MOVES)
    assert not bus.has_pending(InterruptLevel.BETWEEN_DIALOGS)


async def test_drain_at_level_empty_returns_empty_list():
    bus = EventBus()
    result = await bus.drain_at_level(InterruptLevel.PREEMPTIVE)
    assert result == []


async def test_has_pending_false_when_queue_empty():
    bus = EventBus()
    assert not bus.has_pending(InterruptLevel.BETWEEN_DIALOGS)


async def test_get_preemptive_returns_highest_priority():
    bus = EventBus()
    ev_low = _make_event(event_type="low", priority=90,
                          interrupt_level=InterruptLevel.PREEMPTIVE)
    ev_high = _make_event(event_type="high", priority=10,
                           interrupt_level=InterruptLevel.PREEMPTIVE)
    await bus.emit(ev_low)
    await bus.emit(ev_high)

    best = await bus.get_preemptive()
    assert best is not None
    assert best.type == "high"

    # The lower-priority event should still be in the queue
    assert bus.has_pending(InterruptLevel.PREEMPTIVE)


async def test_get_preemptive_none_when_empty():
    bus = EventBus()
    assert await bus.get_preemptive() is None


async def test_shutdown_silences_further_emits():
    bus = EventBus()
    bus.shutdown()
    await bus.emit(_make_event())
    assert not bus.has_pending(InterruptLevel.BETWEEN_DIALOGS)


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------

async def test_priority_ordering_lower_value_wins():
    bus = EventBus()
    for priority in [70, 10, 50]:
        await bus.emit(_make_event(priority=priority))

    drained = await bus.drain_at_level(InterruptLevel.BETWEEN_DIALOGS)
    priorities = [e.priority for e in drained]
    assert sorted(priorities) == priorities   # 10, 50, 70


# ---------------------------------------------------------------------------
# Subscriptions: move-level fan-out
# ---------------------------------------------------------------------------

async def test_subscribe_delivers_matching_event():
    bus = EventBus()
    q = bus.subscribe(lambda ev: ev.type == "button_press")
    try:
        await bus.emit(_make_event(event_type="button_press"))
        received = q.get_nowait()
        assert received.type == "button_press"
    finally:
        bus.unsubscribe(q)


async def test_consumed_event_not_forwarded_to_queue():
    """An event consumed by a subscription must NOT also appear in the priority queue."""
    bus = EventBus()
    q = bus.subscribe(lambda ev: ev.type == "button_press")
    try:
        await bus.emit(_make_event(event_type="button_press"))
        assert not bus.has_pending(InterruptLevel.BETWEEN_DIALOGS)
    finally:
        bus.unsubscribe(q)


async def test_non_matching_event_goes_to_queue():
    bus = EventBus()
    q = bus.subscribe(lambda ev: ev.type == "button_press")
    try:
        await bus.emit(_make_event(event_type="timer_tick"))
        assert bus.has_pending(InterruptLevel.BETWEEN_DIALOGS)
        assert q.empty()
    finally:
        bus.unsubscribe(q)


async def test_unsubscribe_removes_subscription():
    bus = EventBus()
    q = bus.subscribe(lambda ev: True)
    bus.unsubscribe(q)
    await bus.emit(_make_event())
    # After unsubscribe the event should land in the queue, not the subscription q
    assert bus.has_pending(InterruptLevel.BETWEEN_DIALOGS)
    assert q.empty()


async def test_only_first_matching_subscription_receives_event():
    """Each event is delivered to at most one subscription (first match wins)."""
    bus = EventBus()
    q1 = bus.subscribe(lambda ev: ev.type == "x")
    q2 = bus.subscribe(lambda ev: ev.type == "x")
    try:
        await bus.emit(_make_event(event_type="x"))
        assert not q1.empty()
        assert q2.empty()
    finally:
        bus.unsubscribe(q1)
        bus.unsubscribe(q2)


# ---------------------------------------------------------------------------
# Event ordering tiebreaker (seq)
# ---------------------------------------------------------------------------

async def test_seq_tiebreaker_maintains_fifo_for_equal_priority():
    bus = EventBus()
    ev1 = _make_event(event_type="first",  priority=50)
    ev2 = _make_event(event_type="second", priority=50)
    await bus.emit(ev1)
    await bus.emit(ev2)

    drained = await bus.drain_at_level(InterruptLevel.BETWEEN_DIALOGS)
    assert [e.type for e in drained] == ["first", "second"]
