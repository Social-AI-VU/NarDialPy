from typing import Any, Dict, Optional, List, cast

from nardial.interaction_orchestrator import ConversationStdinEOF
from nardial.utils import normalize_text
import re
from time import monotonic
from datetime import datetime, timezone

from nardial.moves import MOVE_SAY, MOVE_ASK_YESNO, MOVE_ASK_OPEN, MOVE_ASK_OPTIONS, MOVE_PLAY_AUDIO, MOVE_MOTION_SEQUENCE, \
    MOVE_ANIMATION, \
    MoveAskYesNo, MoveAskOpen, MoveAskOptions, MovePlayAudio, MoveMotionSequence, MoveAnimation, MoveBranch, \
    MOVE_ANSWER_OPEN, MOVE_ANSWER_YESNO, MOVE_ANSWER_OPTIONS, MoveAskLLM, MOVE_ASK_LLM, MOVE_ANSWER_LLM, \
    MOVE_LLM_FOLLOWUP, MOVE_BRANCH

from enum import Enum


class DialogType(Enum):
    NARRATIVE = "narrative"
    CHITCHAT = "chitchat"
    FUNCTIONAL = "functional"
    LLM_BASED = "llm_based"
    HYBRID_ROUTER = "llm_router"
    INTENT_ROUTER = "intent_router"


MAX_LLM_TURNS = 5


def _listen_until_stdin_eof(agent: Any) -> None:
    """After the LLM or user signals "end", wait until Ctrl+D (stdin EOF) before exiting."""
    while True:
        _, meta = agent.orchestrator.listen(detect_intent=False)
        if meta == "__stdin_eof__":
            raise ConversationStdinEOF


class MiniDialog:
    def __init__(self, dialog_id, moves, dependencies=None, variable_dependencies=None):
        """
        dialog_id: str, unique identifier (e.g. 'pineapple_on_pizza')
        moves: list of dicts, each representing a dialog move
        attributes: dict, extra attributes depending on dialog type
        """
        self.dialog_id = dialog_id
        self.moves = moves
        self.dependencies = dependencies or []
        self.variable_dependencies = variable_dependencies or []

        self.conversation_agent = None
        self.session_history = []
        self.topics_of_interest = []
        self.user_model = {}
        self.current_outcome = None

    def set_conversation_config(self, agent, session_history, topics_of_interest, user_model):
        self.conversation_agent = agent
        self.session_history = session_history if session_history is not None else []
        self.topics_of_interest = topics_of_interest if topics_of_interest is not None else []
        self.user_model = user_model if user_model is not None else {}

    # Helper to read either dict-style or attribute-style moves (supports MoveSay objects)
    @staticmethod
    def _get(move, key, default=None):
        try:
            if isinstance(move, dict):
                return move.get(key, default)
            # Fallback to attribute access for move objects
            return getattr(move, key, default)
        except Exception:
            return default

    @staticmethod
    def add_interest(topics_of_interest, topic):
        if topics_of_interest is None or not topic:
            return
        t = str(topic).strip()
        if not t:
            return
        low = t.lower()
        if all(low != str(x).lower() for x in topics_of_interest):
            topics_of_interest.append(t)

    def _robot_timestamp_monotonic(self):
        try:
            ts = self.conversation_agent.orchestrator.last_robot_speech_start_monotonic
            if isinstance(ts, (int, float)):
                return float(ts)
        except Exception:
            pass
        return monotonic()

    def _record_robot(self, type_name: str, text: str, **extra):
        entry = {
            "role": "robot",
            "type": type_name,
            "text": text,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "timestamp_monotonic": self._robot_timestamp_monotonic(),
        }
        entry.update(extra)
        self.session_history.append(entry)

    def _record_user(self, type_name: str, text: str, **extra):
        entry = {
            "role": "user",
            "type": type_name,
            "text": text,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "timestamp_monotonic": monotonic(),
        }
        entry.update(extra)
        self.session_history.append(entry)

    def _record_system(self, type_name: str, text: str, **extra):
        entry = {
            "role": "system",
            "type": type_name,
            "text": text,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "timestamp_monotonic": monotonic(),
        }
        entry.update(extra)
        self.session_history.append(entry)

    def _store_set_variable(self, move, answer: str):
        if not answer:
            return
        if getattr(move, 'set_variable', None):
            self.user_model[move.set_variable] = self.extract_open_value(answer)

    def _store_interests(self, move, answer: str):
        if answer and getattr(move, 'add_interest_from_answer', False):
            self.add_interest(self.topics_of_interest, answer)
        if getattr(move, 'add_interest_from_variable', None):
            val = self.user_model.get(move.add_interest_from_variable)
            if val:
                self.add_interest(self.topics_of_interest, val)

    @staticmethod
    def extract_open_value(answer: str) -> str:
        """
        General-purpose cleaner for open answers used with set_variable.
        Heuristics (language-agnostic):
        - If quoted text is present, return the first quoted segment.
        - Otherwise, return the last alphabetic token (e.g., 'zebra' from 'my favorite animal is a zebra').
        - Fallback to trimmed original answer if nothing matches.
        """
        if not answer:
            return ""
        text = str(answer).strip()
        # Prefer explicitly quoted content
        m = re.search(r'["\']([^"\']+)["\']', text)
        if m:
            return m.group(1).strip()
        # Fallback: pick the last alphabetic-ish token
        tokens = re.findall(r"[A-Za-z][A-Za-z\-']+", text)
        if tokens:
            return tokens[-1]
        return text

    def run(self, agent, session_history=None, topics_of_interest=None, user_model=None):
        # Execute mini dialogs, sending speech to the device and logging events.
        self.set_conversation_config(agent, session_history, topics_of_interest, user_model)

        idx = 0

        while idx < len(self.moves):
            move = self.moves[idx]
            self._dispatch_move(move)
            idx += 1

    def _resolve_outcome(self, move, answer) -> None:
        """Resolve and store ``current_outcome`` from the declarative outcome fields.

        Resolution order:
        1. Exact match: if ``answer`` appears as a key in ``outcomes``, use that label.
        2. Wildcard: if ``"*"`` is a key in ``outcomes`` and ``answer`` is non-empty,
           use that label (useful for free-text ``ask_open`` answers).
        3. Default: ``default_outcome`` is used when the answer is empty/None, or
           when no exact or wildcard match is found.
        """
        outcomes = self._get(move, 'outcomes') or {}
        default_outcome = self._get(move, 'default_outcome')
        if answer and answer in outcomes:
            self.current_outcome = outcomes[answer]
        elif answer and "*" in outcomes:
            self.current_outcome = outcomes["*"]
        else:
            self.current_outcome = default_outcome

    def handle_move_branch(self, move) -> None:
        """Execute the sub-moves for the matching case of a ``branch`` move."""
        move = MoveBranch.from_dict(move)
        if move.on == "outcome":
            key = self.current_outcome
        else:
            key = self.user_model.get(move.on)
        case_moves = move.cases.get(key, [])
        for sub_move in case_moves:
            self._dispatch_move(sub_move)

    def _dispatch_move(self, move) -> None:
        """Execute a single move dict."""
        move_type = self._get(move, 'type')
        if move_type == MOVE_SAY:
            self.handle_move_say(move)
        elif move_type == MOVE_ASK_YESNO:
            answer = self.handle_move_ask_yesno(move)
            self._resolve_outcome(move, answer)
        elif move_type == MOVE_ASK_OPEN:
            answer = self.handle_move_ask_open(move)
            self._resolve_outcome(move, answer)
        elif move_type == MOVE_ASK_OPTIONS:
            answer = self.handle_move_ask_options(move)
            self._resolve_outcome(move, answer)
        elif move_type == MOVE_BRANCH:
            self.handle_move_branch(move)
        elif move_type == MOVE_PLAY_AUDIO:
            self.handle_move_play_audio(move)
        elif move_type == MOVE_MOTION_SEQUENCE:
            self.handle_move_motion_sequence(move)
        elif move_type == MOVE_ANIMATION:
            self.handle_move_animation(move)
        elif move_type == MOVE_ASK_LLM:
                self.handle_move_ask_llm(move)

    def _generate_llm_followup(self, user_answer: str, system_prompt: str):
        """Call the LLM to generate a contextual followup to the user's answer and speak it."""
        context_messages = self.conversation_agent.orchestrator.reconstruct_conversation(
            self.session_history
        )
        llm_text = self.conversation_agent.ask_llm(
            user_prompt=user_answer,
            context_messages=context_messages,
            system_prompt=system_prompt,
            llm_call_purpose="llm_followup",
        )
        print(f"[LLM] followup_response={llm_text!r}")
        if llm_text:
            self.conversation_agent.say(llm_text)
            self._record_robot(
                MOVE_LLM_FOLLOWUP,
                llm_text,
                token_usage=getattr(self.conversation_agent.orchestrator, "last_llm_usage", None),
            )

    def handle_move_say(self, move):
        text = self._get(move, 'text')
        for var, value in self.user_model.items():
            text = text.replace(f"%{var}%", str(value))
        self.conversation_agent.say(text)
        self._record_robot(MOVE_SAY, text)

    def handle_move_ask_yesno(self, move):
        move = MoveAskYesNo.from_dict(move)
        answer = self.conversation_agent.ask_yesno(move.text)
        self._record_robot(MOVE_ASK_YESNO, move.text)
        self._record_user(MOVE_ANSWER_YESNO, answer)
        print(f"User answered: {answer}")

        # store answer and interest if configured
        self._store_set_variable(move, answer)
        if answer == "yes" and getattr(move, 'add_interest', None):
            self.add_interest(self.topics_of_interest, move.add_interest)

        # Optional LLM-generated followup response
        if move.llm_followup:
            self._generate_llm_followup(user_answer=answer or "", system_prompt=move.llm_followup)

        return answer

    def handle_move_ask_open(self, move):
        move = MoveAskOpen.from_dict(move)
        answer = self.conversation_agent.ask_open(move.text)
        self._record_robot(MOVE_ASK_OPEN, move.text)
        self._record_user(MOVE_ANSWER_OPEN, answer)
        print(f"User answered: {answer}")

        # store answer and interests if configured
        self._store_set_variable(move, answer)
        self._store_interests(move, answer)

        # Optional LLM-generated followup response
        if move.llm_followup:
            self._generate_llm_followup(user_answer=answer or "", system_prompt=move.llm_followup)

        return answer

    def handle_move_ask_options(self, move):
        move = MoveAskOptions.from_dict(move)
        answer = self.conversation_agent.ask_options(move.text, move.options)
        self._record_robot(MOVE_ASK_OPTIONS, move.text, options=move.options)
        self._record_user(MOVE_ANSWER_OPTIONS, answer)
        print(f"User answered: {answer}")

        # store answer if configured
        self._store_set_variable(move, answer)
        self._store_interests(move, answer)

        # Optional LLM-generated followup response
        if move.llm_followup:
            self._generate_llm_followup(user_answer=answer or "", system_prompt=move.llm_followup)

        return answer

    def handle_move_play_audio(self, move):
        move = MovePlayAudio.from_dict(move)
        self.conversation_agent.play_audio(move.audio_file)
        self._record_robot(MOVE_PLAY_AUDIO, "Played audio. ", audio_file=move.audio_file)

    def handle_move_motion_sequence(self, move):
        move = MoveMotionSequence.from_dict(move)
        self.conversation_agent.play_motion_sequence(move.sequence_file)
        self._record_robot(MOVE_MOTION_SEQUENCE, "Played motion sequence.", motion_sequence_file=move.sequence_file)

    def handle_move_animation(self, move):
        move = MoveAnimation.from_dict(move)
        self.conversation_agent.play_animation(move.animation_name)
        self._record_robot(MOVE_ANIMATION, "Played animation. ", animation_name=move.animation_name)

    def handle_move_ask_llm(self, move):
        move = MoveAskLLM.from_dict(move)
        self._run_llm_exchange(
            prompt=move.prompt,
            max_turns=move.max_turns or MAX_LLM_TURNS,
            set_variable=move.set_variable,
            quit_phrases=move.quit_phrases,
            quit_signal=move.quit_signal,
            llm_call_purpose="ask_llm_move",
        )

    def _run_llm_exchange(self, prompt: str, max_turns: int, set_variable: Optional[str] = None,
                          quit_phrases: Optional[List[str]] = None, quit_signal: Optional[str] = None,
                          speak_first: bool = True, duration: Optional[float] = None,
                          rag_enabled: bool = False, rag_index_name: Optional[str] = None,
                          llm_call_purpose: str = "llm_dialog"):
        user_input = ""
        start_time = monotonic()

        def remaining_time():
            if duration is None:
                return None
            return max(0.0, duration - (monotonic() - start_time))

        agent = cast(Any, self.conversation_agent)
        if not speak_first:
            timeout = remaining_time()
            if timeout is not None and timeout <= 0:
                return
            reply, meta = agent.orchestrator.listen(timeout=timeout or 10)
            if meta == "__stdin_eof__":
                raise ConversationStdinEOF
            user_input = reply or ""
            self._record_user(MOVE_ANSWER_LLM, user_input)

        for _ in range(max_turns or MAX_LLM_TURNS):
            timeout = remaining_time()
            if timeout is not None and timeout <= 0:
                return
            llm_text = agent.ask_llm(
                user_prompt=user_input,
                context_messages=agent.orchestrator.reconstruct_conversation(self.session_history),
                system_prompt=prompt,
                rag_enabled=rag_enabled,
                rag_index_name=rag_index_name,
                llm_call_purpose=llm_call_purpose,
            )
            print(f"[LLM] response={llm_text!r}")
            if llm_text is None:
                continue

            # If the LLM embeds a quit signal, speak any remaining content and stop
            if quit_signal and quit_signal in llm_text:
                print(f"[LLM] quit_signal_detected={quit_signal!r}; waiting for Ctrl+D (stdin EOF) to exit block")
                clean = llm_text.replace(quit_signal, "").strip()
                if clean:
                    agent.say(clean)
                    self._record_robot(
                        MOVE_SAY,
                        clean,
                        token_usage=getattr(agent.orchestrator, "last_llm_usage", None),
                    )
                _listen_until_stdin_eof(agent)
                return

            # Ask the user the LLM's text and listen for reply
            agent.say(llm_text)
            timeout = remaining_time()
            if timeout is not None and timeout <= 0:
                return
            user_input, meta = agent.orchestrator.listen(timeout=timeout or 10)
            if meta == "__stdin_eof__":
                raise ConversationStdinEOF
            if not user_input:
                user_input = ""

            # Record the exchange using the provided record types
            self._record_robot(
                MOVE_ASK_LLM,
                llm_text,
                token_usage=getattr(agent.orchestrator, "last_llm_usage", None),
            )
            self._record_user(MOVE_ANSWER_LLM, user_input)

            # Optionally store a variable from user's answer
            if set_variable and user_input:
                self.user_model[set_variable] = self.extract_open_value(user_input)

            # Quit phrases no longer end the block; require Ctrl+D (stdin EOF).
            quit_happened = False
            for qp in (quit_phrases or []):
                if not qp:
                    continue
                if qp.lower() in user_input.lower():
                    quit_happened = True
                    break
            if quit_happened:
                print("[LLM] quit_phrase matched; waiting for Ctrl+D (stdin EOF) to exit block")
                _listen_until_stdin_eof(agent)
                return


class FunctionalType(Enum):
    GREETING = "greeting"
    FAREWELL = "farewell"


class FunctionalDialog(MiniDialog):
    def __init__(self, dialog_id, moves, type, dependencies=None):
        # Functional dialogs are utility blocks such as greeting and farewell.
        super().__init__(dialog_id, moves, dependencies)
        self.type = type

    def is_greeting_dialog(self):
        return self.type == FunctionalType.GREETING

    def is_farewell_dialog(self):
        return self.type == FunctionalType.FAREWELL


class NarrativeDialog(MiniDialog):
    def __init__(self, dialog_id, moves, thread, position, dependencies=None, variable_dependencies=None):
        # Narrative dialogs belong to a thread and have an explicit position (order).
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.thread = thread
        self.position = position


class ChitchatDialog(MiniDialog):
    def __init__(
            self,
            dialog_id,
            moves,
            theme,
            topics=None,
            dependencies=None,
            variable_dependencies=None,
            description: str = "",
    ):
        # Chitchat dialogs are short, theme-based interactions that can be biased by topics.
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.theme = theme
        self.topics = topics or []
        self.description = description or ""


class LLMDialog(MiniDialog):
    def __init__(self, dialog_id, moves, prompt, max_turns=None, dependencies=None,
                 variable_dependencies=None, quit_phrases: Optional[List[str]] = None, quit_signal: Optional[str] = None,
                 speak_first: bool = True, duration: Optional[float] = None,
                 rag_enabled: bool = False, rag_index_name: Optional[str] = None):
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.prompt = prompt
        self.max_turns = max_turns or MAX_LLM_TURNS
        self.speak_first = speak_first
        self.duration = duration
        self.rag_enabled = rag_enabled
        self.rag_index_name = rag_index_name
        # Quit phrases (user utterances) and quit signal (LLM-inserted token)
        self.quit_phrases = [p for p in (quit_phrases or []) if p]
        self.quit_signal = quit_signal if quit_signal is not None else "<<QUIT>>"

    def run(self, agent, session_history, topics_of_interest, user_model):
        self.set_conversation_config(agent, session_history, topics_of_interest, user_model)

        self._run_llm_exchange(
            prompt=self.prompt,
            max_turns=self.max_turns,
            set_variable=None,
            quit_phrases=self.quit_phrases,
            quit_signal=self.quit_signal,
            speak_first=self.speak_first,
            duration=self.duration,
            rag_enabled=self.rag_enabled,
            rag_index_name=self.rag_index_name,
            llm_call_purpose="llm_based_dialog",
        )


class IntentRouterDialog(MiniDialog):
    """
    Routes each user turn to a child mini-dialog using Dialogflow intent names (when present),
    then utterance-topic heuristics, then an optional ``fallback_in_character`` child.

    Must be bound to a :class:`nardial.session_manager.SessionManager` via
    ``bind_session_manager`` before ``run`` so child dialogs can reuse eligibility and logging.
    """

    def __init__(
            self,
            child_dialogs: List["MiniDialog"],
            intent_routing: Dict[str, str],
            block_exit_intents: Optional[List[str]] = None,
            dialog_id: Optional[str] = None,
            dependencies=None,
            variable_dependencies=None,
    ):
        auto_id = dialog_id or ("intent_router__" + "__".join(sorted(d.dialog_id for d in child_dialogs)))
        super().__init__(auto_id, moves=[], dependencies=dependencies, variable_dependencies=variable_dependencies)
        self.child_dialogs = list(child_dialogs or [])
        self.intent_routing = dict(intent_routing or {})
        self.block_exit_intents = set(block_exit_intents or ["exit", "goodbye", "done", "stop", "cancel", "finish"])
        self._session_manager = None

    def bind_session_manager(self, session_manager: Any) -> None:
        self._session_manager = session_manager

    def infer_dialog_from_utterance(self, utterance: str, candidates: List["MiniDialog"]):
        text = normalize_text(utterance)
        if not text:
            return None

        scored = []
        for d in candidates:
            topics = [normalize_text(t) for t in getattr(d, "topics", [])]
            if not topics:
                continue
            score = 0
            for topic in topics:
                if topic and topic in text:
                    score += max(2, len(topic.split()))
                else:
                    topic_tokens = [tok for tok in topic.split() if len(tok) > 2]
                    score += sum(1 for tok in topic_tokens if tok in text)
            if score > 0:
                scored.append((score, d))

        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    def run(self, agent, session_history=None, topics_of_interest=None, user_model=None):
        self.set_conversation_config(agent, session_history, topics_of_interest, user_model)
        sm = self._session_manager
        if sm is None:
            raise RuntimeError(
                "IntentRouterDialog requires bind_session_manager(SessionManager) before run()"
            )

        block_map = {d.dialog_id: d for d in self.child_dialogs}
        fallback = block_map.get("fallback_in_character")
        print(f"[ROUTER] Starting intent-routed block with dialogs: {sorted(block_map.keys())}")
        remaining = {
            d.dialog_id
            for d in self.child_dialogs
            if d.dialog_id != "fallback_in_character" and (
                bool(getattr(d, "repeatable", False)) or d.dialog_id not in sm.conversation_state.completed_dialogs
            )
        }

        while remaining:
            utterance, intent = agent.orchestrator.listen()
            if intent == "__stdin_eof__":
                print("[ROUTER] stdin EOF (Ctrl+D); ending intent router block")
                break
            intent_norm = normalize_text(intent)
            utterance_norm = normalize_text(utterance)
            if utterance:
                self._record_user("answer_open", utterance, intent=intent)
            print(
                f"[ROUTER] user_utterance={utterance!r}, raw_intent={intent!r}, "
                f"normalized_intent={intent_norm!r}, remaining={sorted(remaining)}"
            )

            if intent_norm in self.block_exit_intents or utterance_norm in self.block_exit_intents:
                print(
                    f"[ROUTER] Exit intent/utterance ignored (use Ctrl+D / stdin EOF to leave this block): "
                    f"intent={intent_norm!r}, utterance={utterance_norm!r}"
                )
                continue

            target_id = self.intent_routing.get(intent_norm)
            target = block_map.get(target_id) if target_id else None
            if intent_norm:
                print(f"[ROUTER] intent_map lookup: {intent_norm!r} -> {target_id!r}")
            else:
                print("[ROUTER] No intent detected; falling back to utterance-topic routing.")

            if not target:
                candidate_dialogs = [block_map[did] for did in remaining if did in block_map]
                target = self.infer_dialog_from_utterance(utterance_norm, candidate_dialogs)
                print(f"[ROUTER] heuristic match result: {getattr(target, 'dialog_id', None)!r}")

            if not target or target.dialog_id not in remaining:
                if fallback:
                    print("[ROUTER] No valid target; running fallback dialog.")
                    try:
                        sm._run_single_dialog(
                            fallback,
                            self.session_history,
                            allow_repeatable_rerun=bool(getattr(fallback, "repeatable", False)),
                        )
                    except ConversationStdinEOF:
                        print("[ROUTER] stdin EOF (Ctrl+D) during fallback dialog; ending intent router block")
                        break
                else:
                    agent.say("I am not sure how to respond to that. Please ask in a different way.")
                continue

            is_repeatable = bool(getattr(target, "repeatable", False))
            try:
                ran = sm._run_single_dialog(
                    target,
                    self.session_history,
                    allow_repeatable_rerun=is_repeatable,
                )
            except ConversationStdinEOF:
                print("[ROUTER] stdin EOF (Ctrl+D) during child dialog; ending intent router block")
                break
            print(f"[ROUTER] ran dialog={target.dialog_id!r}, repeatable={is_repeatable}, ran={ran}")
            if not is_repeatable and target.dialog_id in remaining and (
                    ran or target.dialog_id in sm.conversation_state.completed_dialogs):
                remaining.remove(target.dialog_id)
                print(f"[ROUTER] removed from remaining: {target.dialog_id!r}")


class LLMRouterDialog(MiniDialog):
    def __init__(self, dialog_id, base_prompt: str, dialogs: List[MiniDialog], dependencies=None, variable_dependencies=None,
                 done_phrases: Optional[List[str]] = None, rag_enabled: bool = True, rag_index_name: Optional[str] = None,
                 max_turns: int = 100):
        super().__init__(dialog_id, moves=[], dependencies=dependencies, variable_dependencies=variable_dependencies)
        self.base_prompt = base_prompt or ""
        self.dialogs = dialogs or []
        self.done_phrases = [p for p in (done_phrases or []) if p]
        self.rag_enabled = bool(rag_enabled)
        self.rag_index_name = rag_index_name
        self.max_turns = max(1, int(max_turns or 100))

    def run(self, agent, session_history, topics_of_interest, user_model):
        self.set_conversation_config(agent, session_history, topics_of_interest, user_model)
        # LLM router uses the same graph implementation as the hybrid router.
        from nardial.hybrid_router_graph import run_llm_router_graph
        run_llm_router_graph(
            conversation_agent=self.conversation_agent,
            session_history=self.session_history,
            topics_of_interest=self.topics_of_interest,
            user_model=self.user_model,
            base_prompt=self.base_prompt,
            dialogs=self.dialogs,
            logger=getattr(getattr(self.conversation_agent, "orchestrator", None), "logger", None),
            rag_enabled=self.rag_enabled,
            rag_index_name=self.rag_index_name,
            max_turns=self.max_turns,
        )
