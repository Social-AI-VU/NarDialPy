import json
import os

import numpy as np

from nardial.conversation_agent import ConversationAgent
from nardial.conversation_state import ConversationState
from nardial.dialog_logic import DialogLogic

from nardial.authoring import load_dialogs


class SessionManager:
    def __init__(self, session_agenda: list, agent: ConversationAgent, dialog_json_path: str):
        self.session_agenda = session_agenda
        self.dialogs = self.load_dialogs_from_json(dialog_json_path)
        self.agent = agent

        self.conversation_state = ConversationState(overwrite_with_participant_info=True)
        self.session_id = self.start_session()

        # TODO: For now we just take all dialogs in the session_agenda, but we could also apply some filtering logic here
        self.session_block = self.dialogs

    @staticmethod
    def load_dialogs_from_json(path):
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

    def start_session(self):
        run_id =  os.environ.get("RUN_ID") or f"run_{np.random.randint(1_000_000):06d}"
        session_id = self.conversation_state.start_session(
            # metadata={"thread": thread, "theme": theme},
            participant_id=self.conversation_state.participant_id,
            run_id=run_id
        )
        print(f"[INFO] Started session_id={session_id} run_id={run_id}")
        return session_id

    def run(self):
        session_history = []
        for dialog in self.session_block:
            if not DialogLogic.can_run(dialog, self.conversation_state.completed_dialogs, self.conversation_state.user_model, self.dialogs):
                print(f"[DEBUG] Skipped {dialog.dialog_id} (cannot run now)")
                continue
            self.conversation_state.add_dialog_id(self.session_id, dialog.dialog_id)
            session_history.append({"role": "system", "type": "dialog_start", "dialog_id": dialog.dialog_id})
            dialog.run(self.agent, session_history, self.conversation_state.topics_of_interest, self.conversation_state.user_model)
            session_history.append({"role": "system", "type": "dialog_end", "dialog_id": dialog.dialog_id})
            self.conversation_state.completed_dialogs.append(dialog.dialog_id)

        print(json.dumps(session_history, indent=2))
        print("Topics of interest:", self.conversation_state.topics_of_interest)

        # Condense topics_of_interest into single-word keywords
        topics_of_interest = self.condense_topics(self.conversation_state.topics_of_interest)

        self.conversation_state.add_events(self.session_id, session_history)
        self.conversation_state.end_session(self.session_id,
                                       completed_ids=self.conversation_state.completed_dialogs,
                                       user_model=self.conversation_state.user_model,
                                       topics_of_interest=topics_of_interest)
        self.conversation_state.save()
        print("Conversation state saved.")

    def condense_topics(self, topics_of_interest):
        # Condense topics_of_interest into single-word keywords via GPT (with a simple fallback)
        try:
            topics_of_interest = self.agent.extract_topics_with_gpt(list(topics_of_interest))
            print(f"[DEBUG] Condensed topics: {topics_of_interest}")
        except Exception as e:
            print(f"[WARN] Topic condensation failed: {e}")
        return topics_of_interest

