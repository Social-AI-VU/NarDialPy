import json
import sys
from os.path import abspath, join
import os
import numpy as np

from authoring.loader import load_dialogs
from conversation_state import ConversationState


from src.conversation_agent import ConversationAgent
from src.dialog import DialogLogic

"""
This is a demo show casing a agent-driven conversation utalizating Google Dialogflow, Google TTS, and OpenAI's GTP4

IMPORTANT
First, you need to set-up Google Cloud Console with dialogflow and Google TTS:

1. Dialogflow: https://socialrobotics.atlassian.net/wiki/spaces/CBSR/pages/2205155343/Getting+a+google+dialogflow+key 
2. TTS: https://console.cloud.google.com/apis/api/texttospeech.googleapis.com/ 
2a. note: you need to set-up a paid account with a credit card. You get $300,- free tokens, which is more then enough
for testing this agent. So in practice it will not cost anything.
3. Create a keyfile as instructed in (1) and save it conf/dialogflow/google_keyfile.json
3a. note: never share the keyfile online. 

Secondly you need to configure your dialogflow agent.
4. In your empty dialogflow agent do the following things:
4a. remove all default intents
4b. go to settings -> import and export -> and import the resources/droomrobot_dialogflow_agent.zip into your
dialogflow agent. That gives all the necessary intents and entities that are part of this example (and many more)

Thirdly, you need an openAI key:
5. Generate your personal openai api key here: https://platform.openai.com/api-keys
6. Either add your openai key to your systems variables or
create a .openai_env file in the conf/openai folder and add your key there like this:
OPENAI_API_KEY="your key"

Forth, the redis server, Dialogflow, Google TTS and OpenAI gpt service need to be running:

7. pip install --upgrade social-interaction-cloud[dialogflow,google-tts,openai-gpt]
8. run: conf/redis/redis-server.exe conf/redis/redis.conf
9. run in new terminal: run-dialogflow 
10. run in new terminal: run-google-tts
11. run in new terminal: run-gpt
12. connect a device e.g. desktop, nao, pepper, alphamini
13. Run this script
"""


ALL_HISTORY_FILE = "all_sessions_history.json"
# Load previous sessions history if file exists
if os.path.exists(ALL_HISTORY_FILE):
    with open(ALL_HISTORY_FILE, "r", encoding="utf-8") as f:
        all_sessions_history = json.load(f)
else:
    all_sessions_history = []

if __name__ == '__main__':
    # Select your device
    device = {
        "type": "desktop"
    }
    # device = {
    #     "type": "nao",
    #     "ip": "xxx.xxx.xxx.xxx"
    # }

    agent = ConversationAgent(device, google_keyfile_path=abspath(join("conf", "dialogflow", "google_keyfile.json")),
                              openai_key_path=abspath(join("conf", "openai", ".openai_env")))

    conversation_state = ConversationState()
    conversation_state.load()
    session_history = []
    agent.run()

    # Seed from persisted continuity
    completed_dialogs = set(conversation_state.completed_dialogs)
    user_model = dict(conversation_state.user_model)
    topics_of_interest = list(conversation_state.topics_of_interest)

    # Start new history session (store thread/theme if you like)
    # Participant ID: set via environment variable PARTICIPANT_ID (optional)
    participant_id = os.environ.get("PARTICIPANT_ID") or None
    if participant_id:
        try:
            print(f"[INFO] Using participant_id={participant_id}")
        except Exception:
            pass

    # Override continuity per participant if an ID is provided
    if participant_id:
        pid_completed, pid_topics = DialogLogic.load_participant_continuity(participant_id)  
        # For a new participant (no file), this will be empty -> fresh run
        completed_dialogs = pid_completed or set()
        topics_of_interest = pid_topics or []
        user_model = {}  # avoid leaking variables across participants
        try:
            print(f"[DEBUG] Loaded participant continuity: completed={sorted(list(completed_dialogs))}, topics={topics_of_interest}")
        except Exception:
            pass

    # Create a run_id to group sessions that belong to a single experimental run
    run_id = os.environ.get("RUN_ID") or f"run_{np.random.randint(1_000_000):06d}"
    session_id = conversation_state.start_session(metadata={"thread": "dreams", "theme": "nature"}, participant_id=participant_id, run_id=run_id)
    # Ensure Dialogflow uses a fresh request id per session
    agent.start_new_session()
    try:
        print(f"[INFO] Started session_id={session_id} run_id={run_id}")
    except Exception:
        pass

    # Load dialogs from JSON if available, otherwise fall back to builtin Python list
    dialogs_json_path = abspath(join("assets", "dialogs", "dialogs.json"))
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

    # Build a session plan (greeting → narrative → chitchat → narrative → chitchat → farewell)
    # Auto-pick a thread if the preferred one has no pending narratives
    preferred_thread = "dreams"
    chosen_thread = DialogLogic.auto_select_thread(all_dialogs, preferred_thread, completed_ids=completed_dialogs, user_model=user_model)  
    try:
        print(f"[DEBUG] Narrative thread chosen: {chosen_thread}")
    except Exception:
        pass
    session_block = DialogLogic.select_session_block(all_dialogs, thread=chosen_thread, theme="nature", topics_of_interest=topics_of_interest, completed_ids=completed_dialogs)  
    # Debug: show planned dialogs
    try:
        print("[DEBUG] Planned session block:", [d.dialog_id for d in session_block])
    except Exception:
        pass

    for dialog in session_block:
        if DialogLogic.can_run(dialog, completed_dialogs, user_model, all_dialogs=all_dialogs):  
            # record which dialog runs
            conversation_state.add_dialog_id(session_id, dialog.dialog_id)
            # optional lightweight markers in session_history
            session_history.append({"role": "system", "type": "dialog_start", "dialog_id": dialog.dialog_id})
            dialog.run(agent, session_history, user_model, topics_of_interest)
            session_history.append({"role": "system", "type": "dialog_end", "dialog_id": dialog.dialog_id})
            completed_dialogs.add(dialog.dialog_id)
        else:
            print(f"[DEBUG] Skipped {dialog.dialog_id} (cannot run now)")

    print(json.dumps(session_history, indent=2))
    print("Topics of interest:", topics_of_interest)

    # Condense topics_of_interest into single-word keywords via GPT (with a simple fallback)
    try:
        original_topics = list(topics_of_interest)
        condensed = agent.extract_topics_with_gpt(original_topics)
        topics_of_interest = condensed
        print(f"[DEBUG] Condensed topics: {topics_of_interest}")
    except Exception as e:
        print(f"[WARN] Topic condensation failed: {e}")

    # Keep your legacy file if desired
    all_sessions_history.append(session_history)
    with open(ALL_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(all_sessions_history, f, indent=2)
    print(f"All sessions history saved to {ALL_HISTORY_FILE}")

    # Persist via the new class
    conversation_state.add_events(session_id, session_history)
    conversation_state.end_session(session_id,
                                   completed_ids=completed_dialogs,
                                   user_model=user_model,
                                   topics_of_interest=topics_of_interest)
    conversation_state.save()
    print("Conversation state saved.")

    sys.exit()