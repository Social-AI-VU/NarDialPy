import sys
from os.path import abspath, join
from sic_framework.devices.desktop import Desktop

from nardial.conversation_agent import ConversationAgent
from nardial.session_manager import SessionManager

# setup key files paths
google_keyfile_path = abspath(join("..", "conf", "dialogflow", "google_keyfile.json"))
openai_key_path = abspath(join("..", "conf", "openai", ".openai_env"))
dialog_json_path = abspath(join("..", "examples", "dialogs.json"))


if __name__ == '__main__':
    # Select device
    device = Desktop()
    # device = Pepper(ip="10.0.0.148")

    # Create conversational agent
    agent = ConversationAgent(device, google_keyfile_path=google_keyfile_path, openai_key_path=openai_key_path)

    # all dialogs for now
    session_agenda = ["greeting", "hero_can_dream_1", "dream12", "goodbye"]

    session_manager = SessionManager(
        session_agenda=session_agenda,
        agent=agent,
        dialog_json_path=dialog_json_path,
    )
    session_manager.run()

    sys.exit()
