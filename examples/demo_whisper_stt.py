"""
Local Whisper STT Demo
======================

Demonstrates NarDialPy with the LocalWhisper NLU provider — real speech recognition
running entirely on-device with no internet or API key needed.

Uses mlx-whisper on Mac (Apple Silicon) and faster-whisper on Windows/Linux.

Setup
-----
1. Install the local Whisper backend for your platform:

       # Mac
       pip install mlx-whisper

       # Windows / Linux
       pip install faster-whisper

2. Install SIC local-whisper extras:

       pip install "social-interaction-cloud[local-whisper-stt]"    # Windows/Linux
       pip install "social-interaction-cloud[local-whisper-stt-mac]"  # Mac

3. Start Redis in a separate terminal:

       # Windows
       conf/redis/redis-server.exe conf/redis/redis.conf

       # macOS / Linux
       redis-server conf/redis/redis.conf

4. Start the SIC LocalWhisper service in another terminal:

       run-local-whisper

5. Run this script:

       python examples/demo_whisper_stt.py

The demo will greet you and ask a couple of open-ended questions via speech.
Spoken responses are printed to the terminal.
"""

import sys
from pathlib import Path

from sic_framework.devices.desktop import Desktop
from sic_framework.services.local_whisper_stt.local_whisper import LocalWhisperConf

from nardial.providers.device.desktop import DesktopAdapter
from nardial.providers.tts.null import NullTTSProvider
from nardial.providers.nlu.whisper import LocalWhisperNLUProvider
from nardial.conversation_agent import ConversationAgent
from nardial.session_manager import SessionManager

if __name__ == "__main__":
    # ── Device ────────────────────────────────────────────────────────────────
    desktop = Desktop()
    device = DesktopAdapter(desktop)

    # ── NLU — LocalWhisper ────────────────────────────────────────────────────
    # LocalWhisperConf controls language, model size, and decoding parameters.
    # Set language="en" to skip auto-detection and reduce latency.
    whisper_conf = LocalWhisperConf(
        language="en",
        model_size="large-v3-turbo",
        pause_threshold=0.8,
    )
    nlu = LocalWhisperNLUProvider(conf=whisper_conf, mic=device.get_mic())

    # ── Agent ──────────────────────────────────────────────────────────────────
    agent = ConversationAgent(
        device=device,
        tts_provider=NullTTSProvider(),
        nlu_provider=nlu,
    )

    # ── Session ────────────────────────────────────────────────────────────────
    manager = SessionManager(
        session_agenda=["whisper_demo"],
        agent=agent,
        dialog_json_path=str(Path(__file__).parent / "dialog_json" / "demo_whisper_stt.json"),
        participant_id="whisper_demo_user",
    )
    manager.run()

    sys.exit()
