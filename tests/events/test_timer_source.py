"""Tests for TimerSource."""

import asyncio
import pytest

from nardial.events import EventBus, InterruptLevel, ResumePolicy, TimerSource


async def test_timer_emits_after_delay():
    bus = EventBus()
    source = TimerSource(
        event_type="tick",
        delay_seconds=0.05,
        repeat=False,
    )
    await asyncio.wait_for(source.run(bus), timeout=1.0)

    events = await bus.drain_at_level(InterruptLevel.BETWEEN_DIALOGS)
    assert len(events) == 1
    assert events[0].type == "tick"
    assert events[0].source == source.source_id


async def test_timer_repeat_fires_multiple_times():
    bus = EventBus()
    source = TimerSource(event_type="tick", delay_seconds=0.05, repeat=True)

    task = asyncio.create_task(source.run(bus))
    await asyncio.sleep(0.18)   # allow ~3 ticks (0.05 s each)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    events = await bus.drain_at_level(InterruptLevel.BETWEEN_DIALOGS)
    assert len(events) >= 2


async def test_timer_event_carries_configured_fields():
    bus = EventBus()
    source = TimerSource(
        event_type="my_event",
        delay_seconds=0.05,
        repeat=False,
        interrupt_level=InterruptLevel.BETWEEN_MOVES,
        resume_policy=ResumePolicy.PAUSE,
        handler_dialog_id="handler_1",
        priority=10,
    )
    await asyncio.wait_for(source.run(bus), timeout=1.0)

    events = await bus.drain_at_level(InterruptLevel.BETWEEN_MOVES)
    assert len(events) == 1
    ev = events[0]
    assert ev.type == "my_event"
    assert ev.interrupt_level == InterruptLevel.BETWEEN_MOVES
    assert ev.resume_policy == ResumePolicy.PAUSE
    assert ev.handler_dialog_id == "handler_1"
    assert ev.priority == 10


async def test_timer_does_not_repeat_when_flag_is_false():
    bus = EventBus()
    source = TimerSource(event_type="once", delay_seconds=0.05, repeat=False)

    task = asyncio.create_task(source.run(bus))
    await asyncio.sleep(0.20)
    # Task should have completed naturally (one shot)
    assert task.done()
    task.cancel()

    events = await bus.drain_at_level(InterruptLevel.BETWEEN_DIALOGS)
    assert len(events) == 1
