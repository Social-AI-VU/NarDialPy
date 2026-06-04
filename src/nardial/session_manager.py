import json
import os

import numpy as np
import asyncio

from nardial.conversation_agent import ConversationAgent
from nardial.conversation_state import ConversationState
from nardial.dialog_logic import DialogLogic

from nardial.authoring import load_dialogs
from nardial.events import EventBus


class SessionManager:
    """
    Orchestrates a full conversational session by selecting, running,
    and logging dialogs according to a session agenda and conversation state.
    """

    def __init__(self, session_agenda: list, agent: ConversationAgent, dialog_json_path: str, participant_id=None):
        """
        Initialize a session manager.

        :param session_agenda: Ordered list of dialog IDs to execute.
        :param agent: ConversationAgent responsible for interaction (speech, LLM, etc.).
        :param dialog_json_path: Path to JSON file containing dialog definitions.
        :param participant_id: Optional identifier for the user/participant.
        """
        self.session_agenda = session_agenda
        self.dialogs = self.load_dialogs_from_json(dialog_json_path)
        self.agent = agent

        self.conversation_state = ConversationState(participant_id=participant_id)
        self.session_id = self.start_session()
        self.session_block = self.build_session_block()
        self._bus = None

    @staticmethod
    def load_dialogs_from_json(path):
        """
        Load dialogs from a JSON file using the authoring loader.

        :param path: Path to the dialog JSON file.
        :return: List of dialog objects, or empty list if loading fails.
        """
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
        """
        Initialize a new session in the conversation state.

        Generates or retrieves a run ID, registers the session, and logs it.

        :return: The created session ID.
        """
        run_id = os.environ.get("RUN_ID") or f"run_{np.random.randint(1_000_000):06d}"
        session_id = self.conversation_state.start_session(
            participant_id=self.conversation_state.participant_id,
            run_id=run_id
        )
        print(f"[INFO] Started session_id={session_id} run_id={run_id}")
        return session_id

    def build_session_block(self):
        """
        Construct the ordered list of dialogs to execute in this session.

        If a session agenda is provided, only those dialogs are selected
        (in order). Otherwise, all available dialogs are used.

        :return: List of dialog objects to execute.
        """
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

    def run(self):
        asyncio.run(self.run_async())

    async def run_async(self):
        """
        Execute the session by running each dialog in sequence.

        Handles:
        - Eligibility checks via DialogLogic
        - Session history tracking
        - Updating conversation state (completed dialogs, topics, user model)
        - Persisting session results
        """

        self._bus = EventBus()
        # set_loop must happen before any source task starts so that emit_sync()
        # calls from callback threads (e.g. robot SDK) have a valid loop reference.
        self._bus.set_loop(asyncio.get_running_loop())
        sp = self.agent.orchestrator.screen_provider
        if sp is not None and hasattr(sp, "set_event_bus"):
            sp.set_event_bus(self._bus)

        session_history = []
        for dialog in self.session_block:
            if not DialogLogic.is_dialog_eligible(
                    dialog,
                    self.conversation_state.completed_dialogs,
                    self.conversation_state.user_model,
                    self.dialogs
            ):
                print(f"[DEBUG] Skipped {dialog.dialog_id} (cannot run now)")
                continue

            self.conversation_state.add_dialog_id(self.session_id, dialog.dialog_id)

            session_history.append({
                "role": "system",
                "type": "dialog_start",
                "dialog_id": dialog.dialog_id
            })

            dialog.set_event_bus(self._bus)

            # dialog.run is async; await it directly inside the session event loop.
            try:
                await dialog.run(
                    self.agent,
                    session_history,
                    self.conversation_state.topics_of_interest,
                    self.conversation_state.user_model,
                )
            except Exception as e:
                print(f"[ERROR] Running dialog {dialog.dialog_id} failed: {e}")

            session_history.append({
                "role": "system",
                "type": "dialog_end",
                "dialog_id": dialog.dialog_id
            })

            self.conversation_state.completed_dialogs.append(dialog.dialog_id)

        print(json.dumps(session_history, indent=2))
        print("Topics of interest:", self.conversation_state.topics_of_interest)

        # Condense topics_of_interest into single-word keywords
        topics_of_interest = self.condense_topics(self.conversation_state.topics_of_interest)

        self.conversation_state.add_events(self.session_id, session_history)
        self.conversation_state.end_session(
            self.session_id,
            completed_ids=self.conversation_state.completed_dialogs,
            user_model=self.conversation_state.user_model,
            topics_of_interest=topics_of_interest
        )
        self.conversation_state.save()

    def condense_topics(self, topics_of_interest):
        """
        Reduce a list of topics of interest into concise keywords using GPT.

        Falls back to the original list if extraction fails.

        :param topics_of_interest: List of topic strings.
        :return: Condensed list of topic keywords.
        """
        try:
            res = self.agent.extract_topics_with_llm(list(topics_of_interest))
            if asyncio.iscoroutine(res):
                try:
                    topics_of_interest = asyncio.run(res)
                except RuntimeError:
                    loop = asyncio.get_event_loop()
                    future = asyncio.run_coroutine_threadsafe(res, loop)
                    topics_of_interest = future.result()
            else:
                topics_of_interest = res
                print(f"[DEBUG] Condensed topics: {topics_of_interest}")
        except Exception as e:
            print(f"[WARN] Topic condensation failed: {e}")
        return topics_of_interest
