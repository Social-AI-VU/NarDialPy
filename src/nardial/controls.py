"""Session-wide controls: pause/resume and skipping a listen, bound to input triggers.

Example config (passed as ``InteractionConfig(controls=...)``)::

    {
        "start_paused": True,          # wait for toggle_pause before the first speech or listen
        "toggle_pause": ["space"],     # keyboard keys...
        "skip_listen": ["s"],
    }

A trigger is a keyboard key name, or ``{"<event type>": "<value>"}`` for other
input sources (e.g. ``{"robot_button": "head_front"}`` once such a source exists).
"""

from __future__ import annotations

import asyncio
import logging

from nardial.events.bus import EventBus
from nardial.events.sources import KeyboardSource

logger = logging.getLogger(__name__)

ACTIONS = ("toggle_pause", "skip_listen")


class SessionControl:
    """Maps input events to actions and lets the orchestrator honour pause/skip."""

    def __init__(self, config: dict):
        config = dict(config or {})
        unknown = set(config) - set(ACTIONS) - {"start_paused"}
        if unknown:
            raise ValueError(f"Unknown controls: {sorted(unknown)}. Allowed: {list(ACTIONS)} and 'start_paused'.")

        # (event type, value) -> action
        self.bindings: dict[tuple[str, str], str] = {}
        for action in ACTIONS:
            for trigger in config.get(action) or []:
                if isinstance(trigger, str):
                    trigger = {KeyboardSource.event_type: trigger}
                for event_type, value in trigger.items():
                    self.bindings[(event_type, str(value).lower())] = action

        event_types = {event_type for event_type, _ in self.bindings}
        self.sources = [KeyboardSource()] if KeyboardSource.event_type in event_types else []

        self._running = asyncio.Event()
        self._paused = asyncio.Event()
        self._skip = asyncio.Event()
        if config.get("start_paused"):
            self._paused.set()
        else:
            self._running.set()

        self._bus: EventBus | None = None
        self._sub = None
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @property
    def started(self) -> bool:
        return self._task is not None

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def pause(self) -> None:
        self._running.clear()
        self._paused.set()
        print(f"[INFO] Session paused. Press {self._triggers_for('toggle_pause')} to continue.")

    def resume(self) -> None:
        self._paused.clear()
        self._running.set()
        print("[INFO] Session resumed.")

    def toggle_pause(self) -> None:
        self.resume() if self.paused else self.pause()

    def skip_listen(self) -> None:
        """Stop the current listen early, keeping what was heard so far. No-op when not listening."""
        self._skip.set()

    def action_for(self, event) -> str | None:
        """The action bound to ``event``, or None."""
        if not isinstance(event.data, dict):
            return None
        return self.bindings.get((event.type, str(event.data.get("value")).lower()))

    def handle(self, event) -> None:
        action = self.action_for(event)
        if action is not None:
            getattr(self, action)()

    def _triggers_for(self, action: str) -> str:
        return " / ".join(value for (_, value), a in self.bindings.items() if a == action) or "(no trigger)"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, bus: EventBus) -> None:
        """Listen for bound input events on ``bus`` and start the input sources."""
        self._bus = bus
        self._sub = bus.subscribe(lambda ev: self.action_for(ev) is not None)
        self._task = asyncio.create_task(self._consume())
        for source in self.sources:
            source.start(bus)
        if self.paused:
            print(f"[INFO] Session starts paused. Press {self._triggers_for('toggle_pause')} to start.")

    async def stop(self) -> None:
        for source in self.sources:
            source.stop()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._bus is not None and self._sub is not None:
            self._bus.unsubscribe(self._sub)
            self._sub = None

    async def _consume(self) -> None:
        while True:
            event = await self._sub.get()
            try:
                self.handle(event)
            except Exception:
                logger.exception("SessionControl: handling %r failed", event)

    # ------------------------------------------------------------------
    # Used by the orchestrator
    # ------------------------------------------------------------------

    async def wait_until_running(self) -> None:
        await self._running.wait()

    async def run(self, make_coro, on_stop=None, stop_grace_seconds: float = 3.0):
        """Run ``make_coro()`` and return its result, honouring pause and skip.

        Without ``on_stop`` (speech), a pause cancels the coroutine and starts it
        again from scratch after resume, so the robot repeats the sentence
        instead of finishing it mid-word.

        With ``on_stop`` (listening), both a pause and ``skip_listen`` call it to
        make the coroutine finish early (e.g. stop listening, keeping the audio
        so far) and return the coroutine's result. After a pause, that result is
        held until resume, so the dialog continues after the listen. If the
        coroutine has not finished within ``stop_grace_seconds`` it is cancelled
        and ``None`` is returned.
        """
        while True:
            await self._running.wait()
            self._skip.clear()
            task = asyncio.ensure_future(make_coro())
            waiters = {asyncio.ensure_future(self._paused.wait())}
            if on_stop is not None:
                waiters.add(asyncio.ensure_future(self._skip.wait()))
            stopped = False
            try:
                await asyncio.wait({task, *waiters}, return_when=asyncio.FIRST_COMPLETED)
                if task.done():
                    return task.result()
                if on_stop is not None:
                    # Paused or skipped: ask the work to finish early and keep its result.
                    on_stop()
                    await asyncio.wait({task}, timeout=stop_grace_seconds)
                    stopped = True
            finally:
                for waiter in waiters:
                    waiter.cancel()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            if stopped:
                await self._running.wait()  # after a pause, continue only once resumed
                return None if task.cancelled() else task.result()
            # Paused speech: loop around, wait for resume and start again.
