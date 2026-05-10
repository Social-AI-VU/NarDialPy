"""EventBus — dual-mode event routing for NarDialPy sessions.

Two consumption modes
---------------------
Session-level (priority queue):
    Sources call ``emit()`` / ``emit_sync()``; the ``SessionManager`` drains
    events at checkpoints using ``drain_at_level()`` or ``get_preemptive()``.

Move-level (subscriptions):
    ``DialogRuntime`` calls ``subscribe()`` before a wait-move and
    ``unsubscribe()`` in a ``finally`` block.  A matched event is delivered
    directly to the subscriber queue and is NOT forwarded to the priority
    queue, preventing double-handling.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from nardial.events.types import Event, InterruptLevel

logger = logging.getLogger(__name__)


class EventBus:
    """Central event router for a single dialog session.

    Thread-safety note: ``emit_sync`` is safe to call from threads other than
    the asyncio event-loop thread (e.g. robot SDK callbacks).  All other
    methods must be called from within the running event loop.
    """

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[Event] = asyncio.PriorityQueue()
        # Each subscription is a (predicate, delivery_queue) pair.
        self._subscriptions: list[tuple[Callable[[Event], bool], asyncio.Queue[Event]]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # Session-level: priority queue
    # ------------------------------------------------------------------

    async def emit(self, event: Event) -> None:
        """Emit an event.

        Matched subscriptions consume the event first; if no subscription
        matches it is placed on the priority queue for session-level handling.
        """
        if self._closed:
            return
        consumed = await self._deliver_to_subscribers(event)
        if not consumed:
            await self._queue.put(event)

    def emit_sync(self, event: Event) -> None:
        """Thread-safe emit for use from non-asyncio threads.

        Schedules ``emit`` on the running event loop via
        ``call_soon_threadsafe``.  Call ``set_loop()`` (or ensure the bus is
        first touched from the loop) before using this from a thread.
        """
        loop = self._loop or asyncio.get_event_loop()
        loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(self.emit(event))
        )

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Explicitly bind the bus to an event loop (required for ``emit_sync``)."""
        self._loop = loop

    def has_pending(self, level: InterruptLevel) -> bool:
        """Return True if any queued event has ``interrupt_level == level``."""
        # asyncio.PriorityQueue stores items in a private `_queue` heap list.
        return any(e.interrupt_level == level for e in self._queue._queue)  # type: ignore[attr-defined]

    async def drain_at_level(self, level: InterruptLevel) -> list[Event]:
        """Remove and return all queued events at exactly ``level`` (non-blocking).

        Events at other levels are re-enqueued.
        """
        matched: list[Event] = []
        remaining: list[Event] = []
        while not self._queue.empty():
            try:
                ev = self._queue.get_nowait()
                (matched if ev.interrupt_level == level else remaining).append(ev)
            except asyncio.QueueEmpty:
                break
        for ev in remaining:
            await self._queue.put(ev)
        return matched

    async def get_preemptive(self) -> Event | None:
        """Return the highest-priority PREEMPTIVE event, or None if none queued.

        Any other PREEMPTIVE events are re-enqueued.
        """
        events = await self.drain_at_level(InterruptLevel.PREEMPTIVE)
        if not events:
            return None
        best = min(events, key=lambda e: (e.priority, e.seq))
        for ev in events:
            if ev is not best:
                await self._queue.put(ev)
        return best

    # ------------------------------------------------------------------
    # Move-level: subscriptions
    # ------------------------------------------------------------------

    def subscribe(self, predicate: Callable[[Event], bool]) -> asyncio.Queue[Event]:
        """Register a move-level subscription.

        Returns an ``asyncio.Queue`` that receives matching events.  The caller
        **must** call ``unsubscribe(queue)`` when done — use a ``finally``
        block to guarantee clean-up.
        """
        q: asyncio.Queue[Event] = asyncio.Queue()
        self._subscriptions.append((predicate, q))
        return q

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        """Remove the subscription associated with ``queue``."""
        self._subscriptions = [
            (p, q) for p, q in self._subscriptions if q is not queue
        ]

    async def _deliver_to_subscribers(self, event: Event) -> bool:
        """Try to deliver ``event`` to the first matching subscription.

        Returns True if consumed (caller should not enqueue it).
        """
        for predicate, q in self._subscriptions:
            try:
                if predicate(event):
                    await q.put(event)
                    return True
            except Exception:
                logger.exception("EventBus: subscription predicate raised")
        return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Mark the bus as closed; subsequent ``emit`` calls are no-ops."""
        self._closed = True
