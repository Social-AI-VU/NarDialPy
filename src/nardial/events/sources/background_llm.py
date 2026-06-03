"""Background LLM event source.

Runs a speculative LLM call concurrently with the ongoing dialog and emits an
event carrying the result when the call completes.  The ``SessionManager`` can
then inject the response into the conversation at the next BETWEEN_MOVES
checkpoint (using PAUSE resume policy so the interrupted dialog resumes).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

from nardial.events.bus import EventBus
from nardial.events.source import EventSource
from nardial.events.types import Event, InterruptLevel, ResumePolicy

logger = logging.getLogger(__name__)


class BackgroundLLMSource(EventSource):
    """Fire-and-forget LLM source that emits the result as a single event.

    Parameters
    ----------
    llm_coro_factory : callable
        A zero-argument async callable that returns the LLM response string
        (or None if the call failed).  Called exactly once when the source runs.
    event_type : str
        ``Event.type`` string for the emitted event.
    interrupt_level : InterruptLevel
        Interrupt granularity for the emitted event.
    resume_policy : ResumePolicy
        Resume policy for the emitted event.  Defaults to ``PAUSE`` so the
        interrupted dialog continues after the handler has spoken the LLM text.
    handler_dialog_id : str or None
        Handler dialog to execute when the event fires.
    priority : int
        Priority in the bus queue.
    """

    def __init__(
        self,
        llm_coro_factory: Callable[[], Coroutine[Any, Any, str | None]],
        event_type: str = "llm_ready",
        *,
        interrupt_level: InterruptLevel = InterruptLevel.BETWEEN_MOVES,
        resume_policy: ResumePolicy = ResumePolicy.PAUSE,
        handler_dialog_id: str | None = None,
        priority: int = 40,
    ) -> None:
        self._factory = llm_coro_factory
        self._event_type = event_type
        self._interrupt_level = interrupt_level
        self._resume_policy = resume_policy
        self._handler_dialog_id = handler_dialog_id
        self._priority = priority

    @property
    def source_id(self) -> str:
        return f"BackgroundLLMSource({self._event_type})"

    async def run(self, bus: EventBus) -> None:
        """Execute the LLM coroutine, then emit a result event.  One-shot."""
        try:
            result = await self._factory()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("BackgroundLLMSource: LLM call failed — %s", exc)
            result = None

        event = Event(
            priority=self._priority,
            type=self._event_type,
            source=self.source_id,
            data={"text": result},
            interrupt_level=self._interrupt_level,
            resume_policy=self._resume_policy,
            handler_dialog_id=self._handler_dialog_id,
        )
        logger.debug(
            "BackgroundLLMSource emitting %r (result length=%s)",
            event.type,
            len(result) if result else 0,
        )
        await bus.emit(event)