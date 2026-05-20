import json
import os
from datetime import datetime, timezone
from typing import Callable, Optional

import numpy as np

from nardial.conversation_agent import ConversationAgent
from nardial.conversation_state import ConversationState
from nardial.dialog_logic import DialogLogic

from nardial.authoring import load_dialogs
from nardial.mini_dialogs import IntentRouterDialog
from nardial.interaction_orchestrator import ConversationStdinEOF, ConversationWebEnd
from nardial.transcript import ObservableTranscript
from nardial.utils import normalize_text


class SessionManager:
    """
    Orchestrates a full conversational session by selecting, running,
    and logging dialogs according to a session agenda and conversation state.
    """

    def __init__(
            self,
            session_agenda: list,
            agent: ConversationAgent,
            dialog_json_path: str,
            participant_id=None,
            block_exit_intents: list[str] | None = None):
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
        auto_intent_routing = {}
        for d in self.dialogs:
            intent_name = normalize_text(getattr(d, "intent", None))
            if intent_name:
                auto_intent_routing[intent_name] = d.dialog_id
        self.intent_routing = dict(auto_intent_routing)
        self.block_exit_intents = set(block_exit_intents or ["exit", "goodbye", "done", "stop", "cancel", "finish"])

        self.conversation_state = ConversationState(participant_id=participant_id)
        self.session_id = self.start_session()
        self.session_block = self.build_session_block()

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
        session_block = []
        for agenda_item in self.session_agenda:
            if isinstance(agenda_item, list):
                block = [dialog_map[did] for did in agenda_item if did in dialog_map]
                router = IntentRouterDialog(
                    child_dialogs=block,
                    intent_routing=self.intent_routing,
                    block_exit_intents=list(self.block_exit_intents),
                )
                session_block.append(router)
                continue
            if agenda_item in dialog_map:
                session_block.append(dialog_map[agenda_item])

        return session_block

    def _log_dialog_start(self, session_history, dialog):
        session_history.append({
            "role": "system",
            "type": "dialog_start",
            "dialog_id": dialog.dialog_id,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })

    def _log_dialog_end(self, session_history, dialog):
        session_history.append({
            "role": "system",
            "type": "dialog_end",
            "dialog_id": dialog.dialog_id,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })

    @staticmethod
    def _compute_detailed_transcript_summary(session_history):
        robot_events = [ev for ev in session_history if ev.get("role") == "robot" and isinstance(ev.get("timestamp_monotonic"), (int, float))]
        user_events = [ev for ev in session_history if ev.get("role") == "user" and isinstance(ev.get("timestamp_monotonic"), (int, float))]

        total_interaction_duration_seconds = None
        if robot_events:
            total_interaction_duration_seconds = round(
                float(robot_events[-1]["timestamp_monotonic"]) - float(robot_events[0]["timestamp_monotonic"]),
                3,
            )

        # Exchange count: number of user utterances that occur after robot starts speaking.
        exchanges = 0
        if robot_events:
            first_robot_ts = float(robot_events[0]["timestamp_monotonic"])
            exchanges = sum(1 for ev in user_events if float(ev["timestamp_monotonic"]) >= first_robot_ts)
        else:
            exchanges = len(user_events)

        agent_thinking_latency_per_exchange_seconds = []
        for user_ev in user_events:
            user_ts = float(user_ev["timestamp_monotonic"])
            next_robot = next(
                (
                    ev for ev in robot_events
                    if float(ev["timestamp_monotonic"]) >= user_ts
                ),
                None
            )
            if not next_robot:
                continue
            agent_thinking_latency_per_exchange_seconds.append(
                round(float(next_robot["timestamp_monotonic"]) - user_ts, 3)
            )

        return {
            "total_interaction_duration_seconds": total_interaction_duration_seconds,
            "number_of_exchanges": exchanges,
            "agent_thinking_latency_per_exchange_seconds": agent_thinking_latency_per_exchange_seconds,
            "agent_thinking_latency_avg_seconds": round(
                sum(agent_thinking_latency_per_exchange_seconds) / len(agent_thinking_latency_per_exchange_seconds), 3
            )
            if agent_thinking_latency_per_exchange_seconds else None,
        }

    def _run_single_dialog(self, dialog, session_history, allow_repeatable_rerun=False):
        completed_for_check = list(self.conversation_state.completed_dialogs)
        if allow_repeatable_rerun and bool(getattr(dialog, "repeatable", False)):
            # Repeatable dialogs may run multiple times within a block; bypass only the
            # "already completed" gate while still enforcing dependencies/variables.
            completed_for_check = [d for d in completed_for_check if d != dialog.dialog_id]

        if not DialogLogic.is_dialog_eligible(
                dialog,
                completed_for_check,
                self.conversation_state.user_model,
                self.dialogs
        ):
            print(f"[DEBUG] Skipped {dialog.dialog_id} (cannot run now)")
            return False

        self.conversation_state.add_dialog_id(self.session_id, dialog.dialog_id)
        self._log_dialog_start(session_history, dialog)
        completed_ok = False
        try:
            dialog.run(
                self.agent,
                session_history,
                self.conversation_state.topics_of_interest,
                self.conversation_state.user_model
            )
            completed_ok = True
        finally:
            self._log_dialog_end(session_history, dialog)
        if completed_ok:
            self.conversation_state.completed_dialogs.append(dialog.dialog_id)
        return True

    def run(self, transcript_listener: Optional[Callable[[dict], None]] = None):
        """
        Execute the session by running each dialog in sequence.

        Handles:
        - Eligibility checks via DialogLogic
        - Session history tracking
        - Updating conversation state (completed dialogs, topics, user model)
        - Persisting session results

        :param transcript_listener: Optional callback invoked for each transcript entry
            appended during the session (user, robot, and system events).
        """
        if transcript_listener is not None:
            session_history = ObservableTranscript(on_append=transcript_listener)
        else:
            session_history = []
        orch = self.agent.orchestrator
        orch.transcript_append = session_history.append
        try:
            for agenda_item in self.session_block:
                if isinstance(agenda_item, IntentRouterDialog):
                    agenda_item.bind_session_manager(self)
                try:
                    self._run_single_dialog(agenda_item, session_history)
                except ConversationStdinEOF:
                    print("[SESSION] stdin EOF (Ctrl+D); stopping session agenda early")
                    break
                except ConversationWebEnd:
                    print("[SESSION] User ended conversation via web UI; continuing to remaining agenda")
        finally:
            orch.transcript_append = None
            try:
                orch.stop_spacebar_pause_aux()
                orch._maybe_start_stdin_space_aux_thread()
            except Exception:
                pass

        print(json.dumps(session_history, indent=2))
        print("Topics of interest:", self.conversation_state.topics_of_interest)

        # Condense topics_of_interest into single-word keywords
        topics_of_interest = self.condense_topics(self.conversation_state.topics_of_interest)

        self.conversation_state.add_events(self.session_id, session_history)
        extra_summary = None
        if bool(getattr(self.agent.orchestrator.interaction_conf, "detailed_transcript", False)):
            extra_summary = self._compute_detailed_transcript_summary(session_history)
        self.conversation_state.end_session(
            self.session_id,
            completed_ids=self.conversation_state.completed_dialogs,
            user_model=self.conversation_state.user_model,
            topics_of_interest=topics_of_interest,
            extra_summary=extra_summary,
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
            topics_of_interest = self.agent.extract_topics_with_gpt(list(topics_of_interest))
            print(f"[DEBUG] Condensed topics: {topics_of_interest}")
        except Exception as e:
            print(f"[WARN] Topic condensation failed: {e}")
        return topics_of_interest
