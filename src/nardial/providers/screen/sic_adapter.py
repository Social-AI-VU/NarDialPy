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

if TYPE_CHECKING:
    from nardial.events.bus import EventBus

logger = logging.getLogger(__name__)


class SICScreenAdapter:
    """Screen provider that drives a SIC ``Webserver`` connector.

    Parameters
    ----------
    webserver : Webserver
        An already-instantiated SIC ``Webserver`` connector.  The caller is
        responsible for its lifecycle (creation and teardown).
    """

    def __init__(self, webserver) -> None:
        self._webserver = webserver
        self._bus: "EventBus | None" = None
        # Register the SIC callback immediately. If _bus is None when a click
        # arrives the event is dropped with a WARNING (see _on_button_clicked).
        self._webserver.register_callback(self._on_button_clicked)

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
        """Display an image from a local path or URL."""
        html = self.create_image_page(src)
        await self.show_html(html)

    def _resolve_image_src(self, image_path: str) -> str:
        """Resolve an image path to a browser-usable src.

        - If the path is an absolute URL (http/https/data) it is returned unchanged.
        - If the file exists inside the package web static dir it is rewritten to
          the webserver's /static/... URL so the webserver can serve it.
        - Otherwise, if a matching file exists on disk (project root, examples,
          or absolute path), it is embedded as a base64 data URI so the browser
          will display it without requiring the webserver to expose the file.
        - If nothing is found, the original image_path is returned unchanged.
        """
        if not image_path:
            return image_path
        image_path = str(image_path)
        lowered = image_path.lower()
        if lowered.startswith("http://") or lowered.startswith("https://") or lowered.startswith("data:"):
            return image_path

        # Attempt to find the file on disk. Consider common locations:
        #  - packaged web static dir (served at /static/...)
        #  - project root / examples / provided relative path
        try:
            this_file = Path(__file__).resolve()
            # project root: ../../../../ (src/nardial/providers/screen -> go up 4)
            project_root = this_file.parents[4]
        except Exception:
            project_root = Path(".")

        # 1) Check packaged web static dir (src/nardial/providers/screen/web/static)
        web_static = Path(__file__).resolve().parent / "web" / "static"
        candidate = web_static / image_path
        if candidate.exists():
            # expose via the webserver's /static/ path
            # normalize forward slashes for the URL
            rel = candidate.relative_to(web_static).as_posix()
            return f"/static/{rel}"

        # 2) Check project locations: project_root / image_path and project_root / examples / image_path
        candidates = [
            project_root / image_path,
            project_root / "examples" / image_path,
            Path(image_path),
        ]
        for c in candidates:
            if c.exists():
                try:
                    mime, _ = mimetypes.guess_type(str(c))
                    if not mime:
                        mime = "application/octet-stream"
                    data = c.read_bytes()
                    b64 = base64.b64encode(data).decode("ascii")
                    return f"data:{mime};base64,{b64}"
                except Exception:
                    logger.exception("Failed to embed image '%s' as data URI", c)
                    break

        # Nothing found — return original path and let the browser attempt to load it.
        return image_path

    def create_image_page(self, image_path: str):
        """Create HTML page showing current image."""
        resolved_src = self._resolve_image_src(image_path)
        return f"""<!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Image</title>
                    <style>
                        body {{
                            margin: 0;
                            padding: 0;
                            background-color: #000;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            height: 100vh;
                            overflow: hidden;
                        }}
                        img {{
                            max-width: 100%;
                            max-height: 100%;
                            object-fit: contain;
                        }}
                    </style>
                </head>
                <body>
                    <img src="{resolved_src}" alt="Displayed Image">
                </body>
                </html>
                """

    async def show_video(self, src: str) -> None:
        """Display a video from a local path or an embeddable URL."""
        self._send_screen({"type": "video", "src": src})

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
        """No-op — the SIC ``Webserver`` connector is managed by the caller."""
