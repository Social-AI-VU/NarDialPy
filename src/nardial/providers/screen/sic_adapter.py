"""SIC-backed screen provider for NarDialPy.

Wraps a SIC ``Webserver`` connector and drives a browser-based display via
Socket.IO.  All SIC imports are deferred to method bodies so the module can be
imported without SIC installed — the imports are only resolved when a method is
actually called.

Wire-up summary
---------------
1. Create a SIC ``Webserver`` connector externally (with ``WebserverConf``).
2. Pass it to ``SICScreenAdapter(webserver=...)``.
3. Pass the adapter to ``ConversationAgent(screen_provider=...)``.
4. ``SessionManager.run_async()`` automatically calls ``set_event_bus()`` so
   browser button clicks are forwarded to the NarDialPy ``EventBus``.

EventBus bridge
---------------
The SIC ``Webserver`` emits ``ButtonClicked`` messages when the browser sends a
``sic/button_clicked`` Socket.IO event.  ``_on_button_clicked`` translates these
into NarDialPy ``Event`` objects (``type="web_input"``) and pushes them via
``EventBus.emit_sync()`` — which is thread-safe because SIC callbacks run in
non-asyncio threads.  If ``set_event_bus`` has not been called yet, clicks are
logged as warnings and dropped.

Socket.IO message contract
--------------------------
Display commands go as ``WebInfoMessage(label="screen", message={...})``.
Input commands go as ``WebInfoMessage(label="input", message={...})``.
Transcript lines go as ``WebInfoMessage(label="transcript", message={"role":..., "text":...})``.
Robot speech also sends a ``TranscriptMessage`` for backward compatibility with
other SIC consumers that may already subscribe to ``sic/transcript``.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING

from nardial.events.types import Event, InterruptLevel, ResumePolicy
from nardial.providers import ScreenProvider

if TYPE_CHECKING:
    from nardial.events.bus import EventBus

logger = logging.getLogger(__name__)


class SICScreenAdapter(ScreenProvider):
    """Screen provider that drives a SIC ``Webserver`` connector.

    Parameters
    ----------
    webserver : Webserver
        An already-instantiated SIC ``Webserver`` connector.  The caller is
        responsible for its lifecycle (creation and teardown).
    assets_root : str, optional
        Optional base directory used to resolve ``assets/<relative-path>`` sources.
        Resolved files are sent as ``data:`` URLs (no symlink/copy required).
    """

    def __init__(self, webserver,  assets_root: Path = None) -> None:
        self._webserver = webserver
        self._bus: "EventBus | None" = None
        # Register the SIC callback immediately. If _bus is None when a click
        # arrives the event is dropped with a WARNING (see _on_button_clicked).
        self._webserver.register_callback(self._on_button_clicked)

        # Optional root for "assets/<path>" lookups.
        self._assets_root = Path(assets_root).resolve() if assets_root else None

    def _resolve_media_src(self, src: str) -> str:
        if not src:
            return src

        src = str(src)

        # Already valid for browser
        if src.startswith(("http://", "https://", "data:")):
            return src

        media_path: Path | None = None

        if src.startswith("assets/"):
            if not self._assets_root:
                return src

            relative = src[len("assets/"):].strip("/")
            candidate = (self._assets_root / relative).resolve()
            try:
                candidate.relative_to(self._assets_root)
            except ValueError:
                logger.warning("Rejected asset path outside assets_root: %s", src)
                return src
            media_path = candidate
        else:
            media_path = Path(src).expanduser()
            if not media_path.is_absolute():
                media_path = media_path.resolve()

        if not media_path.is_file():
            return src

        try:
            mime_type = mimetypes.guess_type(str(media_path))[0] or "application/octet-stream"
            encoded = base64.b64encode(media_path.read_bytes()).decode("ascii")
            return f"data:{mime_type};base64,{encoded}"
        except Exception:
            logger.exception("Failed to read media file for %s", src)
            return src

    # ------------------------------------------------------------------
    # EventBus wiring (called by SessionManager.run_async)
    # ------------------------------------------------------------------

    def set_event_bus(self, bus: "EventBus") -> None:
        """Wire this adapter to an ``EventBus`` so button clicks become events.

        Called automatically by ``SessionManager.run_async()`` after the bus is
        created and ``set_loop()`` has been called — guaranteeing that
        ``emit_sync`` is thread-safe before the first click can arrive.

        Parameters
        ----------
        bus : EventBus
            The session's shared event bus.
        """
        self._bus = bus

    # ------------------------------------------------------------------
    # SIC callback — runs in a non-asyncio thread
    # ------------------------------------------------------------------

    def _on_button_clicked(self, message) -> None:
        """Translate a SIC ``ButtonClicked`` message into a NarDialPy event.

        Expected ``message.button`` format (sent by the JS frontend)::

            {"type": "web_input", "value": "<chosen_option>"}

        If the ``EventBus`` has not been set yet, the click is logged as a
        warning and dropped rather than raising.
        """
        if self._bus is None:
            logger.warning(
                "SICScreenAdapter: received button click but EventBus is not set — dropped. "
                "Ensure set_event_bus() is called before the session starts "
                "(SessionManager.run_async() does this automatically)."
            )
            return
        try:
            button_data = message.button or {}
            event = Event(
                priority=50,
                type=button_data.get("type", "web_input"),
                source="screen",
                data={"value": button_data.get("value")},
                interrupt_level=InterruptLevel.BETWEEN_MOVES,
                resume_policy=ResumePolicy.DISCARD,
            )
            self._bus.emit_sync(event)
        except Exception:
            logger.exception("SICScreenAdapter._on_button_clicked: unexpected error")

    # ------------------------------------------------------------------
    # Internal send helpers
    # ------------------------------------------------------------------

    def _send_screen(self, payload: dict) -> None:
        """Send a ``WebInfoMessage`` with ``label="screen"`` to drive the display area."""
        from sic_framework.services.webserver.webserver_service import WebInfoMessage
        self._webserver.send_message(WebInfoMessage(label="screen", message=payload))

    def _send_input(self, payload: dict) -> None:
        """Send a ``WebInfoMessage`` with ``label="input"`` to drive the input area."""
        from sic_framework.services.webserver.webserver_service import WebInfoMessage
        self._webserver.send_message(WebInfoMessage(label="input", message=payload))

    def _send_transcript(self, role: str, text: str) -> None:
        """Send a role-tagged transcript line for display in the conversation log."""
        from sic_framework.services.webserver.webserver_service import WebInfoMessage
        self._webserver.send_message(
            WebInfoMessage(label="transcript", message={"role": role, "text": text})
        )

    # ------------------------------------------------------------------
    # ScreenProvider protocol methods
    # ------------------------------------------------------------------

    async def show_transcript(self, text: str) -> None:
        """Display the robot's spoken text in the conversation log.

        Sends both a ``TranscriptMessage`` (for SIC backward compatibility with
        consumers that subscribe to ``sic/transcript``) and a role-tagged
        ``WebInfoMessage`` that the frontend uses for the conversation log.
        """
        from sic_framework.services.webserver.webserver_service import TranscriptMessage
        self._webserver.send_message(TranscriptMessage(transcript=text))
        self._send_transcript("robot", text)

    async def show_user_transcript(self, text: str) -> None:
        """Display the user's recognised speech in the conversation log."""
        self._send_transcript("user", text)

    async def show_image(self, src: str) -> None:
        """Display an image from a local path or URL. """
        resolved = self._resolve_media_src(src)
        self._send_screen({"type": "image", "src": resolved})

    async def show_video(self, src: str) -> None:
        """Display a video from a local path or an embeddable URL."""
        resolved = self._resolve_media_src(src)
        self._send_screen({"type": "video", "src": resolved})

    async def show_iframe(self, url: str) -> None:
        """Embed an external URL in an iframe on the screen."""
        self._send_screen({"type": "iframe", "src": url})

    async def show_html(self, html: str) -> None:
        """Render a raw HTML snippet in the display area."""
        logger.debug("SICScreenAdapter.show_html called (%d chars)", len(html) if html is not None else 0)
        self._send_screen({"type": "html", "content": html})

    async def show_buttons(self, options: list[str]) -> None:
        """Display a row of clickable buttons, one per option."""
        self._send_input({"type": "buttons", "options": options})

    async def show_text_input(self, prompt: str = "") -> None:
        """Show a text-input field with an optional placeholder."""
        self._send_input({"type": "text_input", "prompt": prompt})

    async def hide_input(self) -> None:
        """Hide the current input widget."""
        self._send_input({"type": "none"})

    async def black(self) -> None:
        """Set the display to blank/black."""
        self._send_screen({"type": "black"})

    async def close(self) -> None:
        # No other shutdown actions here; the webserver is owned by the caller.
        pass
