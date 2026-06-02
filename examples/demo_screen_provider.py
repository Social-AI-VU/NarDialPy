"""
Screen Provider Demo
====================

Demonstrates the NarDialPy screen provider: transcript display, images, iframes,
HTML snippets, and interactive buttons — all driven from a dialog JSON file.

No cloud services are required: spoken text is printed to the terminal
(NullTTSProvider) and NLU input is read from the keyboard (WrittenKeywordNLUProvider).

Setup
-----
1. Install the webserver extra (Flask + Flask-SocketIO):

       pip install "nardial[webserver]"

2. Start Redis in a separate terminal:

       # Windows
       conf/redis/redis-server.exe conf/redis/redis.conf

       # macOS / Linux
       redis-server conf/redis/redis.conf

3. Start the SIC webserver in another separate terminal:

       run-webserver

4. Run this script:

       python examples/demo_screen_provider.py

5. Open your browser to:

       http://localhost:5000

The browser window shows the screen output. The terminal shows the transcript and
prompts you for keyboard input when the dialog asks a question.
"""

import sys
from pathlib import Path

from sic_framework.devices.desktop import Desktop
from sic_framework.services.webserver.webserver_service import Webserver, WebserverConf

from nardial.providers.device.desktop import DesktopAdapter
from nardial.providers.tts.null import NullTTSProvider
from nardial.providers.nlu.written_keyword import WrittenKeywordNLUProvider
from nardial.providers.screen.sic_adapter import SICScreenAdapter
from nardial.conversation_agent import ConversationAgent
from nardial.session_manager import SessionManager

# Locate NarDialPy's built-in screen frontend (templates + static) using the
# installed package path so this works for both editable and regular installs.
import nardial.providers.screen as _screen_pkg
_WEB_DIR = Path(_screen_pkg.__file__).parent / "web"

if __name__ == "__main__":
    # ── Device ────────────────────────────────────────────────────────────────
    desktop = Desktop()
    device = DesktopAdapter(desktop)

    # ── Screen provider ────────────────────────────────────────────────────────
    # The SIC Webserver must be running (run-webserver) before this line.
    # WebserverConf tells it which HTML/CSS/JS to serve — pointing at the
    # NarDialPy screen frontend bundled with the package.
    webserver = Webserver(
        conf=WebserverConf(
            templates_dir=str(_WEB_DIR / "templates"),
            static_dir=str(_WEB_DIR / "static"),
            port=5001,
        )
    )
    screen = SICScreenAdapter(webserver=webserver)

    # ── Agent ──────────────────────────────────────────────────────────────────
    agent = ConversationAgent(
        device=device,
        tts_provider=NullTTSProvider(),
        nlu_provider=WrittenKeywordNLUProvider(),
        screen_provider=screen,
    )

    # ── Session ────────────────────────────────────────────────────────────────
    manager = SessionManager(
        session_agenda=["screen_demo"],
        agent=agent,
        dialog_json_path=str(Path(__file__).parent / "screen_demo_dialogs.json"),
        participant_id="screen_demo_user",
    )
    manager.run()

    sys.exit()