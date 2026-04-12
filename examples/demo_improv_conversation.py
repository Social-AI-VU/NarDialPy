import sys
from os.path import abspath, join
from sic_framework.devices.desktop import Desktop

from nardial.conversation_agent import ConversationAgent
from nardial.session_manager import SessionManager
from pathlib import Path
from nardial.improvisation_graph import save_improvisation_graph_mermaid, improvisation_graph_mermaid

save_improvisation_graph_mermaid(Path("../examples/improvisation_graph.mmd"))
print(improvisation_graph_mermaid())

# setup key files paths
google_keyfile_path = abspath(join("..", "conf", "dialogflow", "google_keyfile.json"))
openai_key_path = abspath(join("..", "conf", "openai", ".openai_env"))
dialog_json_path = abspath(join("..", "examples", "improv.json"))


if __name__ == '__main__':
    # Select device
    device = Desktop()
    # device = Pepper(ip="10.0.0.148")

    # Read environment variables from .env file
    from dotenv import load_dotenv
    load_dotenv(abspath(join("..", "conf", ".env")))

    # Create conversational agent
    agent = ConversationAgent(device, 
    google_keyfile_path=google_keyfile_path, 
    openai_key_path=openai_key_path,
    keyboard_input=True)

    # all dialogs for now
    session_agenda = ["greeting", "hero_can_dream_1", "likes_dogs", "improv_animals", "goodbye"]

    session_manager = SessionManager(
        session_agenda=session_agenda,
        agent=agent,
        dialog_json_path=dialog_json_path,
    )
    session_manager.run(
        export_session_graph_mermaid="../examples/session_graph.mmd",
        export_session_graph_png="../examples/session_graph.png",  # optional; may fail offline
    )

    sys.exit()
