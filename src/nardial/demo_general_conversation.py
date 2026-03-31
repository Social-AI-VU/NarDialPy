import json
import sys
from os.path import abspath, join
import os
import numpy as np
from sic_framework.devices.desktop import Desktop

from src.nardial.authoring import load_dialogs
from conversation_state import ConversationState

from src.nardial.conversation_agent import ConversationAgent
from src.nardial.dialog_logic import DialogLogic

# setup key files paths
google_keyfile_path = abspath(join("../..", "conf", "dialogflow", "google_keyfile.json"))
openai_key_path = abspath(join("../..", "conf", "openai", ".openai_env"))


def load_dialogs_from_json():
    path = abspath(join("../..", "assets", "dialogs", "dialogs.json"))

    try:
        dialogs, errors = load_dialogs(path)
        if errors:
            print("[ERROR] Failed to fully load dialogs:", errors)
            return []
        if dialogs:
            print(f"[INFO] Loaded {len(dialogs)} dialogs from {path}")
            return dialogs
        return []
    except Exception as e:
        print(f"[ERROR] Failed to load dialogs: {e}")
        return []

def create_run_id():
    return os.environ.get("RUN_ID") or f"run_{np.random.randint(1_000_000):06d}"


def create_session_block(all_dialogs, thread, theme, conversation_state):
    # Build a session plan (greeting → narrative → chitchat → narrative → chitchat → farewell)
    # Auto-pick a thread if the preferred one has no pending narratives
    chosen_thread = DialogLogic.auto_select_thread(
        all_dialogs,
        thread,
        completed_ids=conversation_state.completed_dialogs,
        user_model=conversation_state.user_model)
    print(f"[DEBUG] Narrative thread chosen: {chosen_thread}")

    session_block = DialogLogic.select_session_block(
        all_dialogs,
        thread=chosen_thread,
        theme=theme,
        topics_of_interest=conversation_state.topics_of_interest,
        completed_ids=conversation_state.completed_dialogs
    )
    print("[DEBUG] Planned session block:", [d.dialog_id for d in session_block])
    return session_block


def condense_topics(agent, topics_of_interest):
    # Condense topics_of_interest into single-word keywords via GPT (with a simple fallback)
    try:
        topics_of_interest = agent.extract_topics_with_gpt(list(topics_of_interest))
        print(f"[DEBUG] Condensed topics: {topics_of_interest}")
    except Exception as e:
        print(f"[WARN] Topic condensation failed: {e}")
    return topics_of_interest


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

    # Load conversation state from conversation_state.json if it exists
    # ConversationState can be overwritten with participant info by setting PARTICIPANT_ID env var before running
    conversation_state = ConversationState(overwrite_with_participant_info=True)

    # Create a run_id to group sessions that belong to a single experimental run
    run_id = create_run_id()
    session_id = conversation_state.start_session(
        metadata={"thread": thread, "theme": theme},
        participant_id=conversation_state.participant_id,
        run_id=run_id
    )
    print(f"[INFO] Started session_id={session_id} run_id={run_id}")

    # Load dialogs from JSON if available, otherwise fall back to builtin Python list
    all_dialogs = load_dialogs_from_json()

    # Build a session block
    session_block = create_session_block(all_dialogs, thread, theme, conversation_state)

    # Run dialogs
    session_history = []
    for dialog in session_block:
        if not DialogLogic.can_run(dialog, conversation_state.completed_dialogs, conversation_state.user_model,
                                   all_dialogs):
            print(f"[DEBUG] Skipped {dialog.dialog_id} (cannot run now)")
            continue
        conversation_state.add_dialog_id(session_id, dialog.dialog_id)
        session_history.append({"role": "system", "type": "dialog_start", "dialog_id": dialog.dialog_id})
        dialog.run(agent, session_history, conversation_state.topics_of_interest, conversation_state.user_model)
        session_history.append({"role": "system", "type": "dialog_end", "dialog_id": dialog.dialog_id})
        conversation_state.completed_dialogs.add(dialog.dialog_id)

    print(json.dumps(session_history, indent=2))
    print("Topics of interest:", conversation_state.topics_of_interest)

    # Condense topics_of_interest into single-word keywords
    topics_of_interest = condense_topics(agent, conversation_state.topics_of_interest)

    # Persist via the new class
    conversation_state.add_events(session_id, session_history)
    conversation_state.end_session(session_id,
                                   completed_ids=conversation_state.completed_dialogs,
                                   user_model=conversation_state.user_model,
                                   topics_of_interest=topics_of_interest)
    conversation_state.save()
    print("Conversation state saved.")

    sys.exit()
