import sys
from os.path import abspath, dirname, join

from sic_framework.devices import Pepper
from sic_framework.devices.common_desktop.desktop_speakers import SpeakersConf
from sic_framework.devices.desktop import Desktop

from nardial.conversation_agent import ConversationAgent
from nardial.interaction_orchestrator import InteractionConfig
from nardial.session_manager import SessionManager

google_keyfile_path = join("..", "conf", "google", "google_keyfile.json")

if __name__ == '__main__':
    device = Desktop(speakers_conf=SpeakersConf(sample_rate=22050))

    interaction_config = InteractionConfig(google_keyfile_path=google_keyfile_path)

    agent = ConversationAgent(device_manager=device, int_config=interaction_config)

    session_manager = SessionManager(
        session_agenda=[],
        agent=agent,
        dialog_json_path="dialog_with_characters.json",
    )

    session_manager.run()

    sys.exit()