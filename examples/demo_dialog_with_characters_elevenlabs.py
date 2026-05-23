import sys

from sic_framework.devices.common_desktop.desktop_speakers import SpeakersConf
from sic_framework.devices.desktop import Desktop

from nardial.conversation_agent import ConversationAgent
from nardial.interaction_orchestrator import InteractionConfig
from nardial.session_manager import SessionManager
from nardial.tts_manager import ElevenLabsTTSConf

if __name__ == '__main__':
    device = Desktop(speakers_conf=SpeakersConf(sample_rate=22050))

    interaction_config = InteractionConfig(
        tts_conf=ElevenLabsTTSConf(
            voice_id="9BWtsMINqrJLrRacOk9x",
            model_id="eleven_flash_v2_5",
            language="en",
        )
    )
    interaction_config.always_regenerate = True

    agent = ConversationAgent(device_manager=device, int_config=interaction_config)

    session_manager = SessionManager(
        session_agenda=[],
        agent=agent,
        dialog_json_path="dialog_with_characters_elevenlabs.json",
    )

    session_manager.run()

    sys.exit()
