"""Input sources: things outside the dialog (keys, robot buttons, ...) that emit bus events.

A source only reports *what* happened, e.g. ``Event(type="keyboard", data={"value": "space"})``.
What that input *does* (pausing, skipping a listen) is decided by
:class:`~nardial.controls.SessionControl`.
"""

from __future__ import annotations

import logging
from typing import Protocol

from nardial.events.bus import EventBus
from nardial.events.types import Event

logger = logging.getLogger(__name__)


class InputSource(Protocol):
    """Emits events onto the session's bus between ``start()`` and ``stop()``."""

    event_type: str

    def start(self, bus: EventBus) -> None: ...

    def stop(self) -> None: ...


def key_name(key) -> str | None:
    """Readable name for a pynput key: ``"a"``, ``"space"``, ``"f5"``."""
    char = getattr(key, "char", None)
    if char:
        return char.lower()
    return getattr(key, "name", None)


class KeyboardSource:
    """Emits ``Event(type="keyboard", data={"value": <key name>})`` for every key press.

    Uses pynput, which listens globally (the terminal does not need focus) on its
    own thread. If pynput cannot start (e.g. no display on a headless Linux
    machine), keyboard controls are disabled with a warning instead of crashing.
    """

    event_type = "keyboard"

    def __init__(self):
        self._listener = None

    def start(self, bus: EventBus) -> None:
        try:
            from pynput import keyboard
        except Exception as e:
            logger.warning("Keyboard controls disabled, pynput is unavailable: %s", e)
            return

        def on_press(key):
            name = key_name(key)
            if name:
                bus.emit_sync(Event(priority=0, type=self.event_type, source="keyboard", data={"value": name}))

        self._listener = keyboard.Listener(on_press=on_press)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
