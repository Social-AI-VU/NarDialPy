"""HTTP webhook event source.

Receives POST requests with a JSON body and forwards them as events onto the
EventBus.  Provides a generic bridge for external systems — including SIC's
web component — until device-specific sources are available.

Expected POST body (all fields optional except ``type``):

.. code-block:: json

    {
        "type": "button_pressed",
        "source": "optional-override",
        "data": {},
        "interrupt_level": "BETWEEN_DIALOGS",
        "resume_policy": "DISCARD",
        "handler_dialog_id": null,
        "priority": 30
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from nardial.events.bus import EventBus
from nardial.events.source import EventSource
from nardial.events.types import Event, InterruptLevel, ResumePolicy

logger = logging.getLogger(__name__)


class WebhookSource(EventSource):
    """Listens on an HTTP port and converts POST payloads to events.

    Parameters
    ----------
    host : str
        Network interface to bind.
    port : int
        TCP port to listen on.
    default_interrupt_level : InterruptLevel
        Applied to events that omit the ``interrupt_level`` field.
    default_priority : int
        Applied to events that omit the ``priority`` field.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        default_interrupt_level: InterruptLevel = InterruptLevel.BETWEEN_DIALOGS,
        default_priority: int = 30,
    ) -> None:
        self._host = host
        self._port = port
        self._default_interrupt_level = default_interrupt_level
        self._default_priority = default_priority
        self._bus: EventBus | None = None

    @property
    def source_id(self) -> str:
        return f"WebhookSource({self._host}:{self._port})"

    async def run(self, bus: EventBus) -> None:
        """Start the HTTP server and serve until cancelled."""
        self._bus = bus
        server = await asyncio.start_server(
            self._handle_connection, self._host, self._port
        )
        addrs = [s.getsockname() for s in server.sockets] if server.sockets else []
        logger.info("WebhookSource listening on %s", addrs)
        try:
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            logger.debug("WebhookSource shutting down")
            raise

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Read a single HTTP POST, parse the JSON body, emit an event."""
        try:
            raw = await reader.read(65536)
            body = self._extract_body(raw)
            if body:
                event = self._parse_event(body)
                if event and self._bus:
                    await self._bus.emit(event)
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
                else:
                    writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 11\r\n\r\nBad Request")
            else:
                writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 11\r\n\r\nBad Request")
        except Exception as exc:
            logger.warning("WebhookSource handler error: %s", exc)
            writer.write(b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 5\r\n\r\nError")
        finally:
            await writer.drain()
            writer.close()
            await writer.wait_closed()

    @staticmethod
    def _extract_body(raw: bytes) -> bytes | None:
        """Split HTTP headers from body; return body bytes or None."""
        sep = b"\r\n\r\n"
        idx = raw.find(sep)
        if idx == -1:
            return None
        return raw[idx + len(sep):]

    def _parse_event(self, body: bytes) -> Event | None:
        """Deserialise ``body`` JSON into an :class:`~nardial.events.types.Event`."""
        try:
            payload: dict[str, Any] = json.loads(body)
        except json.JSONDecodeError as exc:
            logger.warning("WebhookSource: invalid JSON — %s", exc)
            return None
        event_type = payload.get("type")
        if not event_type:
            logger.warning("WebhookSource: payload missing 'type' field")
            return None

        raw_level = payload.get("interrupt_level")
        try:
            interrupt_level = (
                InterruptLevel[raw_level] if isinstance(raw_level, str)
                else self._default_interrupt_level
            )
        except KeyError:
            interrupt_level = self._default_interrupt_level

        raw_policy = payload.get("resume_policy")
        try:
            resume_policy = (
                ResumePolicy[raw_policy] if isinstance(raw_policy, str)
                else ResumePolicy.DISCARD
            )
        except KeyError:
            resume_policy = ResumePolicy.DISCARD

        try:
            priority = int(payload.get("priority", self._default_priority))
        except (TypeError, ValueError):
            logger.warning("WebhookSource: 'priority' must be an integer — rejecting request")
            return None

        return Event(
            priority=priority,
            type=event_type,
            source=payload.get("source", self.source_id),
            data=payload.get("data"),
            interrupt_level=interrupt_level,
            resume_policy=resume_policy,
            handler_dialog_id=payload.get("handler_dialog_id"),
        )
