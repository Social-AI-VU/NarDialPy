import os
import sys
from os.path import abspath, join

from dotenv import load_dotenv
from sic_framework.devices.common_desktop.desktop_speakers import SpeakersConf
from sic_framework.devices.desktop import Desktop

from nardial.providers.device.desktop import DesktopAdapter
from nardial.providers.tts.google import GoogleTTSProvider, GoogleTTSConf
from nardial.providers.nlu.written_keyword import WrittenKeywordNLUProvider
from nardial.conversation_agent import ConversationAgent
from nardial.interaction_orchestrator import InteractionConfig
from nardial.providers.tts.google import GoogleTTSConf
from nardial.session_manager import SessionManager

google_keyfile_path = abspath(join("..", "conf", "google", "google_keyfile.json"))

if __name__ == '__main__':
    # Select device
    desktop = Desktop(speakers_conf=SpeakersConf(sample_rate=22050))
    device = DesktopAdapter(desktop)
    # device = PepperAdapter(Pepper(ip="10.0.0.148"))

    tts_conf = GoogleTTSConf(
        speaking_rate=1.0,
        google_tts_voice_name="en-US-Neural2-C",
    )
    tts = GoogleTTSProvider(conf=tts_conf, device=device, keyfile_path=google_keyfile_path)
    interaction_config = InteractionConfig(post_speech_delay=0, signal_listening_behavior=False)
    nlu = WrittenKeywordNLUProvider()
    agent = ConversationAgent(device=device, tts_provider=tts, nlu_provider=nlu, int_config=interaction_config)

    session_manager = SessionManager(
        session_agenda=[],
        agent=agent,
        dialog_json_path=abspath(join("..", "examples", "dialog_json", "dialog_with_characters_google_tts.json")),
    )
    session_manager.run()

    sys.exit()
