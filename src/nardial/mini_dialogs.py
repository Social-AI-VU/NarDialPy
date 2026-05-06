from typing import List, Optional, cast, Any
import re
from time import monotonic

from nardial.moves import (
    AnyMove,
    MOVE_SAY, MOVE_ASK_YESNO, MOVE_ASK_OPEN, MOVE_ASK_OPTIONS,
    MOVE_PLAY_AUDIO, MOVE_MOTION_SEQUENCE, MOVE_ANIMATION, MOVE_BRANCH, MOVE_ASK_LLM,
    MOVE_ANSWER_OPEN, MOVE_ANSWER_YESNO, MOVE_ANSWER_OPTIONS, MOVE_ANSWER_LLM,
    MOVE_LLM_FOLLOWUP,
    MoveSay, MoveAskYesNo, MoveAskOpen, MoveAskOptions, MoveAskLLM,
    MovePlayAudio, MoveMotionSequence, MoveAnimation, MoveBranch,
)

from enum import Enum


class DialogType(Enum):
    NARRATIVE = "narrative"
    CHITCHAT = "chitchat"
    FUNCTIONAL = "functional"
    LLM_BASED = "llm_based"


MAX_LLM_TURNS = 5


class MiniDialog:
    def __init__(self, dialog_id: str, moves: List[AnyMove], dependencies=None, variable_dependencies=None):
        """
        dialog_id: str, unique identifier (e.g. 'pineapple_on_pizza')
        moves: list of typed move objects representing the dialog steps
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

    def _record_robot(self, type_name: str, text: str, **extra):
        entry = {"role": "robot", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _record_user(self, type_name: str, text: str, **extra):
        entry = {"role": "user", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _record_system(self, type_name: str, text: str, **extra):
        entry = {"role": "system", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _store_set_variable(self, move, answer: str):
        if not answer:
            return
        if getattr(move, "set_variable", None):
            self.user_model[move.set_variable] = self.extract_open_value(answer)

    def _store_interests(self, move, answer: str):
        if answer and getattr(move, "add_interest_from_answer", False):
            self.add_interest(self.topics_of_interest, answer)
        if getattr(move, "add_interest_from_variable", None):
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
        m = re.search(r'["\']([^"\']+)["\']', text)
        if m:
            return m.group(1).strip()
        tokens = re.findall(r"[A-Za-z][A-Za-z\-']+", text)
        if tokens:
            return tokens[-1]
        return text

    def run(self, agent, session_history=None, topics_of_interest=None, user_model=None):
        self.set_conversation_config(agent, session_history, topics_of_interest, user_model)
        for move in self.moves:
            self._dispatch_move(move)

    def _resolve_outcome(self, move, answer) -> None:
        """Resolve and store ``current_outcome`` from the declarative outcome fields.

        Resolution order:
        1. Exact match in ``outcomes``.
        2. Wildcard ``"*"`` if answer is non-empty.
        3. ``default_outcome`` when no match or answer is empty/None.
        """
        outcomes = move.outcomes
        default_outcome = move.default_outcome
        if answer and answer in outcomes:
            self.current_outcome = outcomes[answer]
        elif answer and "*" in outcomes:
            self.current_outcome = outcomes["*"]
        else:
            self.current_outcome = default_outcome

    def handle_move_branch(self, move: MoveBranch) -> None:
        key = self.current_outcome if move.on == "outcome" else self.user_model.get(move.on)
        for sub_move in move.cases.get(key, []):
            self._dispatch_move(sub_move)

    def _dispatch_move(self, move: AnyMove) -> None:
        if move.type == MOVE_SAY:
            self.handle_move_say(move)
        elif move.type == MOVE_ASK_YESNO:
            answer = self.handle_move_ask_yesno(move)
            self._resolve_outcome(move, answer)
        elif move.type == MOVE_ASK_OPEN:
            answer = self.handle_move_ask_open(move)
            self._resolve_outcome(move, answer)
        elif move.type == MOVE_ASK_OPTIONS:
            answer = self.handle_move_ask_options(move)
            self._resolve_outcome(move, answer)
        elif move.type == MOVE_BRANCH:
            self.handle_move_branch(move)
        elif move.type == MOVE_PLAY_AUDIO:
            self.handle_move_play_audio(move)
        elif move.type == MOVE_MOTION_SEQUENCE:
            self.handle_move_motion_sequence(move)
        elif move.type == MOVE_ANIMATION:
            self.handle_move_animation(move)
        elif move.type == MOVE_ASK_LLM:
            self.handle_move_ask_llm(move)

    def _generate_llm_followup(self, user_answer: str, system_prompt: str):
        context_messages = [
            entry.get("text", "") for entry in self.session_history if entry.get("text") is not None
        ]
        llm_text = self.conversation_agent.ask_llm(
            user_prompt=user_answer,
            context_messages=context_messages,
            system_prompt=system_prompt,
        )
        if llm_text:
            self.conversation_agent.say(llm_text)
            self._record_robot(MOVE_LLM_FOLLOWUP, llm_text)

    def handle_move_say(self, move: MoveSay) -> None:
        text = move.text
        for var, value in self.user_model.items():
            text = text.replace(f"%{var}%", str(value))
        self.conversation_agent.say(text)
        self._record_robot(MOVE_SAY, text)

    def handle_move_ask_yesno(self, move: MoveAskYesNo) -> str:
        answer = self.conversation_agent.ask_yesno(move.text)
        self._record_robot(MOVE_ASK_YESNO, move.text)
        self._record_user(MOVE_ANSWER_YESNO, answer)
        print(f"User answered: {answer}")

        self._store_set_variable(move, answer)
        if answer == "yes" and move.add_interest:
            self.add_interest(self.topics_of_interest, move.add_interest)

        if move.llm_followup:
            self._generate_llm_followup(user_answer=answer or "", system_prompt=move.llm_followup)

        return answer

    def handle_move_ask_open(self, move: MoveAskOpen) -> str:
        answer = self.conversation_agent.ask_open(move.text)
        self._record_robot(MOVE_ASK_OPEN, move.text)
        self._record_user(MOVE_ANSWER_OPEN, answer)
        print(f"User answered: {answer}")

        self._store_set_variable(move, answer)
        self._store_interests(move, answer)

        if move.llm_followup:
            self._generate_llm_followup(user_answer=answer or "", system_prompt=move.llm_followup)

        return answer

    def handle_move_ask_options(self, move: MoveAskOptions) -> str:
        answer = self.conversation_agent.ask_options(move.text, move.options)
        self._record_robot(MOVE_ASK_OPTIONS, move.text, options=move.options)
        self._record_user(MOVE_ANSWER_OPTIONS, answer)
        print(f"User answered: {answer}")

        self._store_set_variable(move, answer)
        self._store_interests(move, answer)

        if move.llm_followup:
            self._generate_llm_followup(user_answer=answer or "", system_prompt=move.llm_followup)

        return answer

    def handle_move_play_audio(self, move: MovePlayAudio) -> None:
        self.conversation_agent.play_audio(move.audio)
        self._record_robot(MOVE_PLAY_AUDIO, "Played audio.", audio_file=move.audio)

    def handle_move_motion_sequence(self, move: MoveMotionSequence) -> None:
        self.conversation_agent.play_motion_sequence(move.motion_sequence)
        self._record_robot(MOVE_MOTION_SEQUENCE, "Played motion sequence.", motion_sequence_file=move.motion_sequence)

    def handle_move_animation(self, move: MoveAnimation) -> None:
        self.conversation_agent.play_animation(move.animation_name)
        self._record_robot(MOVE_ANIMATION, "Played animation.", animation_name=move.animation_name)

    def handle_move_ask_llm(self, move: MoveAskLLM) -> None:
        self._run_llm_exchange(
            prompt=move.prompt,
            max_turns=move.max_turns or MAX_LLM_TURNS,
            set_variable=move.set_variable,
            quit_phrases=move.quit_phrases,
            quit_signal=move.quit_signal,
        )

    def _run_llm_exchange(self, prompt: str, max_turns: int, set_variable: Optional[str] = None,
                          quit_phrases: Optional[List[str]] = None, quit_signal: Optional[str] = None,
                          speak_first: bool = True, duration: Optional[float] = None,
                          rag_enabled: bool = False, index_name: Optional[str] = None):
        dialog_history = []
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
            result = agent.orchestrator.listen(timeout=timeout or 10)
            user_input = result.transcript or ""
            self._record_user(MOVE_ANSWER_LLM, user_input)

        for _ in range(max_turns or MAX_LLM_TURNS):
            timeout = remaining_time()
            if timeout is not None and timeout <= 0:
                return
            llm_text = agent.ask_llm(
                user_prompt=user_input,
                context_messages=dialog_history,
                system_prompt=prompt,
                rag_enabled=rag_enabled,
                index_name=index_name,
            )
            if llm_text is None:
                continue

            # If the LLM embeds a quit signal, speak any remaining content and stop
            if quit_signal and quit_signal in llm_text:
                clean = llm_text.replace(quit_signal, "").strip()
                if clean:
                    agent.say(clean)
                    self._record_robot(MOVE_SAY, clean)
                return

            # Ask the user the LLM's text and listen for reply
            agent.say(llm_text)
            timeout = remaining_time()
            if timeout is not None and timeout <= 0:
                return
            result = agent.orchestrator.listen(timeout=timeout or 10)
            user_input = result.transcript or ""

            # Record the exchange using the provided record types
            self._record_robot(MOVE_ASK_LLM, llm_text)
            self._record_user(MOVE_ANSWER_LLM, user_input)

            # Optionally store a variable from user's answer
            if set_variable and user_input:
                self.user_model[set_variable] = self.extract_open_value(user_input)

            # If the user said a configured quit phrase, stop early
            quit_happened = any(
                qp and qp.lower() in user_input.lower() for qp in (quit_phrases or [])
            )
            if quit_happened:
                return

            dialog_history.append(user_input)


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
    def __init__(self, dialog_id, moves, theme, topics=None, dependencies=None, variable_dependencies=None):
        # Chitchat dialogs are short, theme-based interactions that can be biased by topics.
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.theme = theme
        self.topics = topics or []


class LLMDialog(MiniDialog):
    def __init__(self, dialog_id, moves, prompt, max_turns=None, dependencies=None,
                 variable_dependencies=None, quit_phrases: Optional[List[str]] = None,
                 quit_signal: Optional[str] = None, speak_first: bool = True,
                 duration: Optional[float] = None, rag_enabled: bool = False,
                 index_name: Optional[str] = None):
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.prompt = prompt
        self.max_turns = max_turns  # None means use MAX_LLM_TURNS default at runtime
        self.speak_first = speak_first
        self.duration = duration
        self.rag_enabled = rag_enabled
        self.index_name = index_name
        # Quit phrases (user utterances) and quit signal (LLM-inserted token)
        self.quit_phrases = [p for p in (quit_phrases or []) if p]
        self.quit_signal = quit_signal if quit_signal is not None else "<<QUIT>>"

    def run(self, agent, session_history, topics_of_interest, user_model):
        self.set_conversation_config(agent, session_history, topics_of_interest, user_model)
        self._run_llm_exchange(
            prompt=self.prompt,
            max_turns=self.max_turns or MAX_LLM_TURNS,
            set_variable=None,
            quit_phrases=self.quit_phrases,
            quit_signal=self.quit_signal,
            speak_first=self.speak_first,
            duration=self.duration,
            rag_enabled=self.rag_enabled,
            index_name=self.index_name,
        )
