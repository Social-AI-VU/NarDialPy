import json
import os
from pathlib import Path

import numpy as np

from nardial.conversation_agent import ConversationAgent
from nardial.conversation_state import ConversationState

from nardial.authoring import load_dialogs
from nardial.session_graph import (
    run_session_graph,
    save_session_graph_mermaid,
    save_session_graph_png,
)


class SessionManager:
    def __init__(self, session_agenda: list, agent: ConversationAgent, dialog_json_path: str, participant_id=None):
        self.session_agenda = session_agenda
        self.dialogs = self.load_dialogs_from_json(dialog_json_path)
        self.agent = agent

        self.conversation_state = ConversationState(participant_id=participant_id)
        self.session_id = self.start_session()
        self.session_block = self.build_session_block()

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
        run_id = os.environ.get("RUN_ID") or f"run_{np.random.randint(1_000_000):06d}"
        session_id = self.conversation_state.start_session(
            # metadata={"thread": thread, "theme": theme},
            participant_id=self.conversation_state.participant_id,
            run_id=run_id
        )
        print(f"[INFO] Started session_id={session_id} run_id={run_id}")
        return session_id

    def build_session_block(self):
        # Currently, all dialogs from session_agenda are included as-is.
        # This can be extended to apply more advanced selection/crafting logic using DialogLogic utilities
        if len(self.session_agenda) == 0:
            print("[INFO] Session agenda is empty, running all dialogs.")
            return self.dialogs

        dialog_map = {d.dialog_id: d for d in self.dialogs}

        session_block = [
            dialog_map[dialog_id]
            for dialog_id in self.session_agenda
            if dialog_id in dialog_map
        ]

        return session_block

    def run(
            self,
            export_session_graph_mermaid: str | Path | None = None,
            export_session_graph_png: str | Path | None = None,
            session_graph_xray: bool = True,
    ):
        session_history = []
        if export_session_graph_mermaid is not None:
            out = save_session_graph_mermaid(
                self, export_session_graph_mermaid, xray=session_graph_xray)
            print(f"[INFO] Saved session graph (Mermaid) to {out}")
        if export_session_graph_png is not None:
            png_path = save_session_graph_png(
                self, export_session_graph_png, xray=session_graph_xray)
            if png_path:
                print(f"[INFO] Saved session graph (PNG) to {png_path}")
            else:
                print("[WARN] Session graph PNG export failed (try Mermaid file or check langgraph rendering).")
        run_session_graph(self, session_history)

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
