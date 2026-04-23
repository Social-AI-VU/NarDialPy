import sys
from os.path import abspath, dirname, join

from sic_framework.devices import Pepper
from sic_framework.devices.common_desktop.desktop_speakers import SpeakersConf
from sic_framework.devices.desktop import Desktop

from nardial.conversation_agent import ConversationAgent
from nardial.interaction_orchestrator import InteractionConfig
from nardial.session_manager import SessionManager

# setup key files paths (resolved from this file's location)
_BASE_DIR = abspath(join(dirname(__file__), ".."))
google_keyfile_path = join(_BASE_DIR, "conf", "google", "google_keyfile.json")
openai_key_path = join(_BASE_DIR, "conf", "openai", ".openai_env")
dialog_json_path = join(_BASE_DIR, "examples", "structured_conversation_dialogs.json")

if __name__ == '__main__':
    # Select device
    # device = Desktop(speakers_conf=SpeakersConf(sample_rate=22050))

    device = Pepper(ip="10.0.0.148")

    # Create conversational agent
    interaction_config = InteractionConfig(
        google_keyfile_path=google_keyfile_path,
        openai_key_path=openai_key_path,
    )
    agent = ConversationAgent(device_manager=device, int_config=interaction_config)

    # A clear agenda for this structured demo: intro -> planning -> adaptation -> closing
    session_agenda = [
        "welcome_and_name",
        "plan_activity",
        "adapt_to_user_energy",
        "structured_goodbye",
    ]

    session_manager = SessionManager(
        session_agenda=session_agenda,
        agent=agent,
        dialog_json_path=dialog_json_path,
    )
    session_manager.run()

    sys.exit()
