import json
import sys
from os.path import abspath, join
import os
import numpy as np
from sic_framework.devices import Pepper
from sic_framework.devices.desktop import Desktop

from authoring.loader import load_dialogs
from conversation_state import ConversationState

from src.conversation_agent import ConversationAgent
from src.dialog import DialogLogic
from src.session import Session

# setup key files paths
google_keyfile_path = abspath(join("..", "conf", "dialogflow", "google_keyfile.json"))
openai_key_path = abspath(join("..", "conf", "openai", ".openai_env"))


def load_dialogs_from_json():
    dialogs_json_path = abspath(join("..", "assets", "dialogs", "dialogs.json"))
    try:
        all_dialogs, load_errs = load_dialogs(dialogs_json_path)
        if load_errs:
            print("[WARN] Issues while loading dialogs.json:")
            for e in load_errs:
                print(" -", e)
        if all_dialogs:
            print(f"[INFO] Loaded {len(all_dialogs)} dialogs from {dialogs_json_path}")
        else:
            all_dialogs = []
            print("[WARN] No JSON dialogs loaded and builtin dialogs are unavailable. Proceeding with 0 dialogs.")
    except Exception as e:
        all_dialogs = []
        print(f"[WARN] Falling back to empty dialogs due to error: {e}")
    return all_dialogs


def create_run_id():
    return os.environ.get("RUN_ID") or f"run_{np.random.randint(1_000_000):06d}"


def condense_topics(agent, topics_of_interest):
    # Condense topics_of_interest into single-word keywords via GPT (with a simple fallback)
    try:
        topics_of_interest = agent.extract_topics_with_gpt(list(topics_of_interest))
        print(f"[DEBUG] Condensed topics: {topics_of_interest}")
    except Exception as e:
        print(f"[WARN] Topic condensation failed: {e}")
    return topics_of_interest


class ConversationContext:
    def __init__(self, conversation_state: ConversationState):
        conversation_state.load()

        self.completed_dialogs = set(conversation_state.completed_dialogs)
        self.user_model = dict(conversation_state.user_model)
        self.topics_of_interest = list(conversation_state.topics_of_interest)

        # If participant id is provided, overwrite conversation state with participant history
        # Participant ID: set via environment variable PARTICIPANT_ID (optional)
        self.participant_id = os.environ.get("PARTICIPANT_ID") or None
        if not self.participant_id:
            return
        print(f"[INFO] Using participant_id={self.participant_id}")
        pid_completed, pid_topics = DialogLogic.load_participant_continuity(self.participant_id)
        # For a new participant (no file), this will be empty -> fresh run
        self.completed_dialogs = pid_completed or set()
        self.topics_of_interest = pid_topics or []
        self.user_model = {}  # avoid leaking variables across participants
        print(
            f"[DEBUG] Loaded participant continuity: completed={sorted(list(self.completed_dialogs))}, "
            f"topics={self.topics_of_interest}")


if __name__ == '__main__':
    # Select device
    device = Desktop()
    # device = Pepper(ip="10.0.0.148")

    # Create conversational agent
    agent = ConversationAgent(device, google_keyfile_path=google_keyfile_path, openai_key_path=openai_key_path)
    agent.greet()

    # Define thread and theme for the conversation
    thread = "dreams"
    theme = "nature"

    # Load conversation state
    conversation_state = ConversationState()
    conversation_context = ConversationContext(conversation_state)

    # Create a run_id to group sessions that belong to a single experimental run
    run_id = create_run_id()
    session_id = conversation_state.start_session(
        metadata={"thread": thread, "theme": theme},
        participant_id=conversation_context.participant_id,
        run_id=run_id
    )
    print(f"[INFO] Started session_id={session_id} run_id={run_id}")

    # Load dialogs from JSON if available, otherwise fall back to builtin Python list
    all_dialogs = load_dialogs_from_json()

    # Build a Dialog (greeting → narrative → chitchat → narrative → chitchat → farewell)
    dialog = DialogLogic.build_dialog(
        all_dialogs,
        thread,
        theme,
        topics_of_interest=conversation_context.topics_of_interest,
        completed_ids=conversation_context.completed_dialogs,
    )

    # Create and run a Session that executes the Dialog and tracks state
    session = Session(
        dialog,
        completed_dialogs=conversation_context.completed_dialogs,
        user_model=conversation_context.user_model,
        topics_of_interest=conversation_context.topics_of_interest,
    )
    session_history = session.run(agent, all_dialogs)

    # Reflect updated session state back into the conversation context.
    # Session.__init__ makes copies of completed_dialogs, user_model, and
    # topics_of_interest, so mutations inside Session.run() do not propagate to
    # conversation_context automatically — these assignments are required.
    conversation_context.completed_dialogs = session.completed_dialogs
    conversation_context.user_model = session.user_model
    conversation_context.topics_of_interest = session.topics_of_interest

    # Record each executed dialog ID in the persistent session record
    for dialog_id in session.executed_dialog_ids:
        conversation_state.add_dialog_id(session_id, dialog_id)

    print(json.dumps(session_history, indent=2))
    print("Topics of interest:", conversation_context.topics_of_interest)

    # Condense topics_of_interest into single-word keywords
    conversation_context.topics_of_interest = condense_topics(agent, conversation_context.topics_of_interest)

    # Persist via the new class
    conversation_state.add_events(session_id, session_history)
    conversation_state.end_session(session_id,
                                   completed_ids=conversation_context.completed_dialogs,
                                   user_model=conversation_context.user_model,
                                   topics_of_interest=conversation_context.topics_of_interest)
    conversation_state.save()
    print("Conversation state saved.")

    sys.exit()
