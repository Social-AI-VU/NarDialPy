"""EventSource ABC — the interface every event producer must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod

from nardial.events.bus import EventBus


class EventSource(ABC):
    """Abstract base for all event producers.

    Implementations run as asyncio tasks inside ``SessionManager.run_async()``.
    Each source emits :class:`~nardial.events.types.Event` objects onto the
    shared :class:`~nardial.events.bus.EventBus`.

    Contract
    --------
    - ``run()`` must **not** swallow ``asyncio.CancelledError`` — re-raise it
      so the enclosing ``TaskGroup`` can shut down cleanly.
    - Continuous sources (e.g. button listeners) should loop until cancelled.
    - One-shot sources (e.g. a single timer) may return naturally after firing.
    """

    @abstractmethod
    async def run(self, bus: EventBus) -> None:
        """Produce events onto ``bus`` until cancelled or naturally complete.

        Parameters
        ----------
        bus : EventBus
            The shared session bus to emit events onto.
        """

    @property
    def source_id(self) -> str:
        """Unique identifier used as the ``source`` field on emitted events.

        Defaults to the class name; override to provide a more specific ID
        when multiple instances of the same class run concurrently.
        """
        return type(self).__name__
