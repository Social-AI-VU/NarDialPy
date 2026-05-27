import os
import sys
from os.path import abspath, join

from dotenv import load_dotenv
from sic_framework.devices.common_desktop.desktop_speakers import SpeakersConf
from sic_framework.devices.desktop import Desktop

from nardial.providers.device.desktop import DesktopAdapter
from nardial.providers.tts.elevenlabs import ElevenLabsTTSProvider, ElevenLabsTTSConf
from nardial.providers.nlu.written_keyword import WrittenKeywordNLUProvider
from nardial.conversation_agent import ConversationAgent
from nardial.interaction_orchestrator import InteractionConfig
from nardial.session_manager import SessionManager

# setup key file paths
dialog_json_path = abspath(join("..", "examples", "dialogs.json"))

# Path to your Google / Dialogflow credentials
google_keyfile_path = abspath(join("..", "conf", "google", "google_keyfile.json"))

load_dotenv(dotenv_path="../conf/.env")
print("ELEVENLABS_API_KEY is set:", os.getenv("ELEVENLABS_API_KEY"))

if __name__ == '__main__':
    # Select device
    desktop = Desktop(speakers_conf=SpeakersConf(sample_rate=22050))
    device = DesktopAdapter(desktop)
    # device = PepperAdapter(Pepper(ip="10.0.0.148"))

    tts_conf = ElevenLabsTTSConf(
        api_key = os.getenv("ELEVENLABS_API_KEY", ""),
        voice_id="9BWtsMINqrJLrRacOk9x",
        model_id="eleven_flash_v2_5",
        default_mode="batch",
    )
    tts = ElevenLabsTTSProvider(conf=tts_conf,  device=device)
    nlu = WrittenKeywordNLUProvider()

    # Create conversational agent
    interaction_config = InteractionConfig(post_speech_delay=0, signal_listening_behavior=False)
    interaction_config.always_regenerate = True  # For testing: regenerate TTS audio every time instead of caching
    agent = ConversationAgent(device=device, tts_provider=tts, nlu_provider=nlu, int_config=interaction_config)

    session_manager = SessionManager(
        session_agenda=[],
        agent=agent,
        dialog_json_path= abspath(join("..", "examples", "dialog_with_characters_elevenlabs.json")),
        participant_id="1",
    )
    session_manager.run()

    sys.exit()
