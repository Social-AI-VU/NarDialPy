"""Tests for BackgroundLLMSource."""

import asyncio
import pytest

from nardial.events import BackgroundLLMSource, EventBus, InterruptLevel, ResumePolicy


async def test_background_llm_emits_result_event():
    bus = EventBus()
    source = BackgroundLLMSource(
        llm_coro_factory=lambda: asyncio.coroutine(lambda: "Hello!")(),
        event_type="llm_ready",
    )

    async def _factory():
        return "Hello!"

    source = BackgroundLLMSource(llm_coro_factory=_factory)
    await asyncio.wait_for(source.run(bus), timeout=1.0)

    events = await bus.drain_at_level(InterruptLevel.BETWEEN_MOVES)
    assert len(events) == 1
    assert events[0].type == "llm_ready"
    assert events[0].data == {"text": "Hello!"}


async def test_background_llm_defaults_to_pause_resume_policy():
    bus = EventBus()

    async def _factory():
        return "response"

    source = BackgroundLLMSource(llm_coro_factory=_factory)
    await asyncio.wait_for(source.run(bus), timeout=1.0)

    events = await bus.drain_at_level(InterruptLevel.BETWEEN_MOVES)
    assert events[0].resume_policy == ResumePolicy.PAUSE


async def test_background_llm_emits_none_on_factory_exception():
    bus = EventBus()

    async def _failing_factory():
        raise RuntimeError("LLM service unavailable")

    source = BackgroundLLMSource(llm_coro_factory=_failing_factory)
    await asyncio.wait_for(source.run(bus), timeout=1.0)

    events = await bus.drain_at_level(InterruptLevel.BETWEEN_MOVES)
    assert len(events) == 1
    assert events[0].data == {"text": None}


async def test_background_llm_propagates_cancellation():
    bus = EventBus()

    async def _slow_factory():
        await asyncio.sleep(10)
        return "late"

    source = BackgroundLLMSource(llm_coro_factory=_slow_factory)
    task = asyncio.create_task(source.run(bus))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # No event should have been emitted
    assert not bus.has_pending(InterruptLevel.BETWEEN_MOVES)


async def test_background_llm_custom_event_type_and_priority():
    bus = EventBus()

    async def _factory():
        return "custom"

    source = BackgroundLLMSource(
        llm_coro_factory=_factory,
        event_type="custom_llm",
        interrupt_level=InterruptLevel.BETWEEN_DIALOGS,
        resume_policy=ResumePolicy.DISCARD,
        handler_dialog_id="my_handler",
        priority=20,
    )
    await asyncio.wait_for(source.run(bus), timeout=1.0)

    events = await bus.drain_at_level(InterruptLevel.BETWEEN_DIALOGS)
    assert len(events) == 1
    ev = events[0]
    assert ev.type == "custom_llm"
    assert ev.priority == 20
    assert ev.handler_dialog_id == "my_handler"
    assert ev.resume_policy == ResumePolicy.DISCARD
