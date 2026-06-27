"""Pepper tablet screen provider for NarDialPy.

Extends :class:`~nardial.providers.screen.sic_adapter.SICScreenAdapter` with the
extra step of pointing Pepper's built-in tablet webview at the SIC webserver URL.
All display, transcript, input, and event-bus logic is inherited from the parent
class unchanged.

Wire-up summary
---------------
1. Start the SIC webserver with ``host="0.0.0.0"`` so Pepper can reach it over
   the local network — ``localhost`` will not work from the robot's tablet.
2. Determine the host machine's LAN IP (the address Pepper can route to).
3. Create the adapter::

       import socket
       host_ip = socket.gethostbyname(socket.gethostname())

       adapter = PepperTabletScreenAdapter(
           webserver=webserver,
           tablet=pepper.tablet,
           host_ip=host_ip,
           port=5000,
       )

4. Pass it as ``screen_provider`` to :class:`~nardial.conversation_agent.ConversationAgent`.

The adapter sends ``UrlMessage`` to the tablet during construction and
``ClearDisplayMessage`` when ``close()`` is called at session end.

Wi-Fi setup (optional)
----------------------
If the tablet needs to join a specific network before it can reach the webserver,
pass ``wifi_ssid`` (and optionally ``wifi_password`` / ``wifi_security``) to the
constructor.  The connection request is sent before the page URL is opened.
"""

from __future__ import annotations

import logging
from pathlib import Path

from nardial.providers.screen.sic_adapter import SICScreenAdapter

logger = logging.getLogger(__name__)


class PepperTabletScreenAdapter(SICScreenAdapter):
    """Screen provider that drives both a SIC ``Webserver`` and Pepper's built-in tablet.

    Inherits all display, transcript, and input methods from
    :class:`~nardial.providers.screen.sic_adapter.SICScreenAdapter`.  The tablet
    is pointed at ``http://{host_ip}:{port}/`` during construction; its display
    is cleared when the session ends via ``close()``.

    Parameters
    ----------
    webserver : Webserver
        An already-instantiated SIC ``Webserver`` connector.  Must be configured
        with ``host="0.0.0.0"`` so Pepper's tablet can reach it over the LAN.
    tablet : NaoqiTablet
        The ``NaoqiTablet`` connector from ``pepper.tablet``.
    host_ip : str
        IP address of the host machine as seen from Pepper's network.
        Do **not** use ``"localhost"`` or ``"127.0.0.1"`` — Pepper cannot route
        to those from its own network stack.
    port : int
        Port the SIC webserver is listening on (default: 5000).
    wifi_ssid : str or None
        If given, the tablet will attempt to join this Wi-Fi SSID before the
        page is opened.  Leave as ``None`` to skip Wi-Fi setup (default).
    wifi_password : str
        Password for the Wi-Fi network (default: empty string).
    wifi_security : str
        Security type — one of ``"open"``, ``"wep"``, ``"wpa"``, ``"wpa2"``
        (default: ``"wpa2"``).
    assets_root : str or None
        Optional base directory used to resolve ``assets/<relative-path>`` media.
        Files are inlined as ``data:`` URLs by ``SICScreenAdapter``.
    """

    def __init__(
        self,
        webserver,
        tablet,
        host_ip: str,
        port: int = 5000,
        *,
        wifi_ssid: str | None = None,
        wifi_password: str = "",
        wifi_security: str = "wpa2",
        assets_root: Path | None = None,
    ) -> None:
        # Parent registers the button-click callback on the webserver.
        super().__init__(webserver=webserver, assets_root=assets_root)
        self._tablet = tablet

        if wifi_ssid:
            self._connect_tablet_wifi(wifi_ssid, wifi_password, wifi_security)

        self.tablet_url = f"http://{host_ip}:{port}/"
        logger.info("PepperTabletScreenAdapter: opening %s on Pepper tablet", self.tablet_url)
        self._open_on_tablet(self.tablet_url)

    # ------------------------------------------------------------------
    # Internal helpers — all SIC imports deferred so the module can be
    # imported without SIC installed.
    # ------------------------------------------------------------------

    def _connect_tablet_wifi(self, ssid: str, password: str, security: str) -> None:
        """Send a Wi-Fi connection request to Pepper's tablet.

        Failures are logged and swallowed — the session continues regardless.
        """
        from sic_framework.devices.common_pepper.pepper_tablet import WifiConnectRequest
        logger.info("PepperTabletScreenAdapter: connecting tablet to Wi-Fi SSID %r", ssid)
        try:
            self._tablet.request(WifiConnectRequest(
                network_name=ssid,
                network_password=password,
                network_type=security,
            ))
        except Exception:
            logger.exception(
                "PepperTabletScreenAdapter: Wi-Fi connection to %r failed — continuing without it",
                ssid,
            )

    def _open_on_tablet(self, url: str) -> None:
        """Point Pepper's tablet webview at *url*.

        Failures are logged and swallowed — the session continues even if the
        tablet cannot open the page (e.g. connectivity issues).
        """
        from sic_framework.devices.common_pepper.pepper_tablet import UrlMessage
        try:
            self._tablet.send_message(UrlMessage(url))
        except Exception:
            logger.exception("PepperTabletScreenAdapter: failed to open URL on tablet")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Clear Pepper's tablet display, then release parent resources."""
        from sic_framework.devices.common_pepper.pepper_tablet import ClearDisplayMessage
        try:
            self._tablet.send_message(ClearDisplayMessage())
            logger.info("PepperTabletScreenAdapter: tablet display cleared")
        except Exception:
            logger.exception("PepperTabletScreenAdapter: failed to clear tablet display")
        await super().close()