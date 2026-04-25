import sys
import importlib
from os.path import abspath, join

from nardial.conversation_agent import ConversationAgent
from nardial.interaction_orchestrator import InteractionConfig
from nardial.session_manager import SessionManager

# setup key files paths
dialog_json_path = abspath(join("..", "examples", "dialogs.json"))
mcp_desktop = importlib.import_module("sic_framework.mcp.mcp_desktop")

if __name__ == '__main__':
    # Create conversational agent
    interaction_config = InteractionConfig(post_speech_delay=2, keyboard_input=True, device_mcp=mcp_desktop)
    agent = ConversationAgent(device_mcp=mcp_desktop, int_config=interaction_config)

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
