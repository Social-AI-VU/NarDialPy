"""Timer-based event source."""

from __future__ import annotations

import asyncio
import logging

from nardial.events.bus import EventBus
from nardial.events.source import EventSource
from nardial.events.types import Event, InterruptLevel, ResumePolicy

logger = logging.getLogger(__name__)


class TimerSource(EventSource):
    """Emits an event after a fixed delay, optionally repeating.

    Parameters
    ----------
    event_type : str
        ``Event.type`` string for emitted events.
    delay_seconds : float
        Seconds to wait before each emission.
    repeat : bool
        If True, re-arms the timer after each emission until cancelled.
    interrupt_level : InterruptLevel
        Interrupt granularity for emitted events.
    resume_policy : ResumePolicy
        Resume policy for emitted events.
    handler_dialog_id : str or None
        Handler dialog to execute when the event fires.
    priority : int
        Priority in the bus queue (lower = higher priority).
    """

    def __init__(
        self,
        event_type: str,
        delay_seconds: float,
        *,
        repeat: bool = False,
        interrupt_level: InterruptLevel = InterruptLevel.BETWEEN_DIALOGS,
        resume_policy: ResumePolicy = ResumePolicy.DISCARD,
        handler_dialog_id: str | None = None,
        priority: int = 50,
    ) -> None:
        self._event_type = event_type
        self._delay = delay_seconds
        self._repeat = repeat
        self._interrupt_level = interrupt_level
        self._resume_policy = resume_policy
        self._handler_dialog_id = handler_dialog_id
        self._priority = priority

    @property
    def source_id(self) -> str:
        return f"TimerSource({self._event_type})"

    async def run(self, bus: EventBus) -> None:
        """Sleep for the configured delay, emit, then repeat if configured."""
        while True:
            await asyncio.sleep(self._delay)
            event = Event(
                priority=self._priority,
                type=self._event_type,
                source=self.source_id,
                interrupt_level=self._interrupt_level,
                resume_policy=self._resume_policy,
                handler_dialog_id=self._handler_dialog_id,
            )
            logger.debug("TimerSource emitting %r", event.type)
            await bus.emit(event)
            if not self._repeat:
                return