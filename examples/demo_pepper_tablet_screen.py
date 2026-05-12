"""
Pepper Tablet Screen Provider Demo
====================================

Demonstrates the NarDialPy screen provider on Pepper's built-in tablet.
The tablet opens the NarDialPy web frontend via the SIC webserver so all
display commands (transcript, images, buttons) appear on the tablet screen.

Setup
-----
1. Install the webserver extra (Flask + Flask-SocketIO):

       pip install "nardial[webserver]"

2. Start Redis in a separate terminal:

       # Windows
       conf/redis/redis-server.exe conf/redis/redis.conf

       # macOS / Linux
       redis-server conf/redis/redis.conf

3. Start the Dialogflow and Google TTS services:

       run-dialogflow
       run-google-tts

4. Set ROBOT_IP below to your Pepper's IP address, then run this script:

       python examples/demo_pepper_tablet_screen.py

Pepper's tablet will navigate to the NarDialPy screen frontend automatically.
The conversation also plays back through the screen's transcript pane.

Wi-Fi (optional)
----------------
If Pepper's tablet is not already on the same network as your host machine,
fill in WIFI_SSID / WIFI_PASSWORD and the adapter will configure the tablet's
Wi-Fi connection before opening the page.
"""

import socket
import sys
from pathlib import Path

from sic_framework.devices import Pepper
from sic_framework.services.dialogflow.dialogflow import DialogflowConf
from sic_framework.services.webserver.webserver_service import Webserver, WebserverConf

from nardial.providers.device.pepper import PepperAdapter
from nardial.providers.tts.naoqi import NaoqiTTSProvider
from nardial.providers.nlu.dialogflow import DialogflowNLUProvider
from nardial.providers.screen.pepper_tablet import PepperTabletScreenAdapter
from nardial.conversation_agent import ConversationAgent
from nardial.session_manager import SessionManager

# Locate NarDialPy's built-in screen frontend using the installed package path.
import nardial.providers.screen as _screen_pkg
_WEB_DIR = Path(_screen_pkg.__file__).parent / "web"

# ── Configuration ──────────────────────────────────────────────────────────────

ROBOT_IP = "XXX"            # Replace with your Pepper's IP address.
WEB_PORT = 5000

# Optional: fill in to connect Pepper's tablet to Wi-Fi before opening the page.
WIFI_SSID = ""
WIFI_PASSWORD = ""
WIFI_SECURITY = "wpa2"      # One of: "open", "wep", "wpa", "wpa2".

# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Resolve the host machine's LAN IP so Pepper's tablet can reach the webserver.
    # socket.gethostbyname(socket.gethostname()) is usually correct on a single-NIC
    # machine; override manually if your machine has multiple network interfaces.
    host_ip = socket.gethostbyname(socket.gethostname())

    # ── Device ────────────────────────────────────────────────────────────────
    pepper = Pepper(ip=ROBOT_IP)
    device = PepperAdapter(pepper)

    # ── Screen provider ────────────────────────────────────────────────────────
    # host="0.0.0.0" is required: Pepper cannot route to localhost.
    webserver = Webserver(
        conf=WebserverConf(
            host="0.0.0.0",
            port=WEB_PORT,
            templates_dir=str(_WEB_DIR / "templates"),
            static_dir=str(_WEB_DIR / "static"),
        )
    )
    screen = PepperTabletScreenAdapter(
        webserver=webserver,
        tablet=pepper.tablet,
        host_ip=host_ip,
        port=WEB_PORT,
        wifi_ssid=WIFI_SSID or None,
        wifi_password=WIFI_PASSWORD,
        wifi_security=WIFI_SECURITY,
    )

    # ── Providers ──────────────────────────────────────────────────────────────
    tts = NaoqiTTSProvider(device=device)
    nlu = DialogflowNLUProvider(
        conf=DialogflowConf(keyfile="conf/dialogflow/google_keyfile.json"),
        mic=pepper.mic,
    )

    # ── Agent ──────────────────────────────────────────────────────────────────
    agent = ConversationAgent(
        device=device,
        tts_provider=tts,
        nlu_provider=nlu,
        screen_provider=screen,
    )

    # ── Session ────────────────────────────────────────────────────────────────
    manager = SessionManager(
        session_agenda=["screen_demo"],
        agent=agent,
        dialog_json_path=str(Path(__file__).parent / "screen_demo_dialogs.json"),
        participant_id="pepper_tablet_user",
    )
    manager.run()

    sys.exit()
