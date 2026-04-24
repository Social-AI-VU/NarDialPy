import sys
from os.path import abspath, join

from sic_framework.devices.common_desktop.desktop_speakers import SpeakersConf
from sic_framework.devices.desktop import Desktop

from nardial.conversation_agent import ConversationAgent
from nardial.interaction_orchestrator import InteractionConfig
from nardial.session_manager import SessionManager

# setup key files paths
dialog_json_path = abspath(join("..", "examples", "dialogs.json"))

if __name__ == '__main__':
    # Select device
    device = Desktop(speakers_conf=SpeakersConf(sample_rate=22050))
    # device = Pepper(ip="10.0.0.148")

    # Create conversational agent
    interaction_config = InteractionConfig(post_speech_delay=2, keyboard_input=True)
    agent = ConversationAgent(device_manager=device, int_config=interaction_config)

    # all dialogs for now
    session_agenda = ["greeting", "hero_can_dream_1", "dream12", "goodbye"]

    session_manager = SessionManager(
        session_agenda=session_agenda,
        agent=agent,
        dialog_json_path=dialog_json_path,
        participant_id="1",
    )
    session_manager.run()

    sys.exit()
