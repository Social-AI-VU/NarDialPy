from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import Any

from nardial.base_dialog import BaseDialog
from nardial.eligibility import (
    DepsMetRule,
    EligibilityPolicy,
    ExcludeIfSeenRule,
    NarrativeOrderingRule,
    VariableDepsMetRule,
)
from nardial.moves import (
    MOVE_ANIMATION,
    MOVE_ANSWER_LLM,
    MOVE_ANSWER_OPEN,
    MOVE_ANSWER_OPTIONS,
    MOVE_ANSWER_YESNO,
    MOVE_ASK_LLM,
    MOVE_ASK_OPEN,
    MOVE_ASK_OPTIONS,
    MOVE_ASK_YESNO,
    MOVE_LLM_FOLLOWUP,
    MOVE_MOTION_SEQUENCE,
    MOVE_PLAY_AUDIO,
    MOVE_SAY,
    AnyMove,
    MoveAskLLM,
    MoveAskOpen,
    MoveAskOptions,
    MoveAskYesNo,
    MoveAnimation,
    MoveBranch,
    MoveMotionSequence,
    MovePlayAudio,
    MoveSay,
)

logger = logging.getLogger(__name__)


@dataclass
class RunContext:
    """Mutable conversational state accumulated during a single dialog execution.

    The agent (ConversationAgent) is intentionally kept separate — it is a
    stable capability provider, not state. Only data that changes *as the
    dialog runs* belongs here: the growing history, the user model, discovered
    topics, and the outcome of the most recent ask-move.
    """
    session_history: list[dict[str, Any]] = field(default_factory=list)
    topics_of_interest: list[str] = field(default_factory=list)
    user_model: Any = field(default_factory=dict)  # UserModel or plain dict
    current_outcome: str | None = None


class DialogType(Enum):
    NARRATIVE = "narrative"
    CHITCHAT = "chitchat"
    FUNCTIONAL = "functional"
    LLM_BASED = "llm_based"


MAX_LLM_TURNS = 5


def extract_open_value(answer: str) -> str:
    """General-purpose cleaner for open answers used with set_variable.

    Heuristics (language-agnostic):
    - If quoted text is present, return the first quoted segment.
    - Otherwise, return the last alphabetic token (e.g., 'zebra' from
      'my favorite animal is a zebra').
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


def _run_llm_exchange(agent: Any, context: RunContext, prompt: str, max_turns: int,
                      set_variable: str | None = None,
                      quit_phrases: list[str] | None = None,
                      quit_signal: str | None = None,
                      speak_first: bool = True,
                      duration: float | None = None,
                      rag_enabled: bool = False,
                      index_name: str | None = None) -> None:
    """Drive a multi-turn LLM conversation loop.

    Parameters
    ----------
    agent : ConversationAgent
        Provides ask_llm, say, and orchestrator.listen.
    context : RunContext
        Accumulates session history and user model updates.
    prompt : str
        System prompt passed to the LLM on every turn.
    max_turns : int
        Maximum number of LLM turns to execute.
    set_variable : str, optional
        Store the last user answer in context.user_model under this key.
    quit_phrases : list of str, optional
        User utterances that stop the loop early.
    quit_signal : str, optional
        Token the LLM embeds to signal end of conversation.
    speak_first : bool
        If False, listen for the user's opening utterance before the first LLM call.
    duration : float, optional
        Total wall-clock time budget in seconds; the loop stops when time runs out.
    rag_enabled : bool
        Whether to enable retrieval-augmented generation.
    index_name : str, optional
        Vector store index name for RAG queries.
    """
    dialog_history: list[str] = []
    user_input = ""
    start_time = monotonic()

    def remaining_time() -> Optional[float]:
        if duration is None:
            return None
        return max(0.0, duration - (monotonic() - start_time))

    if not speak_first:
        timeout = remaining_time()
        if timeout is not None and timeout <= 0:
            return
        result = agent.orchestrator.listen(timeout=timeout or 10)
        user_input = result.transcript or ""
        context.session_history.append({"role": "user", "type": MOVE_ANSWER_LLM, "text": user_input})

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
                context.session_history.append({"role": "robot", "type": MOVE_SAY, "text": clean})
            return

        # Ask the user the LLM's text and listen for reply
        agent.say(llm_text)
        timeout = remaining_time()
        if timeout is not None and timeout <= 0:
            return
        result = agent.orchestrator.listen(timeout=timeout or 10)
        user_input = result.transcript or ""

        # Record the exchange using the provided record types
        context.session_history.append({"role": "robot", "type": MOVE_ASK_LLM, "text": llm_text})
        context.session_history.append({"role": "user", "type": MOVE_ANSWER_LLM, "text": user_input})

        # Optionally store a variable from user's answer
        if set_variable and user_input:
            context.user_model[set_variable] = extract_open_value(user_input)

        # If the user said a configured quit phrase, stop early
        quit_happened = any(
            qp and qp.lower() in user_input.lower() for qp in (quit_phrases or [])
        )
        if quit_happened:
            return

        dialog_history.append(user_input)


class MiniDialog(BaseDialog):
    # Fallback policy for direct MiniDialog instantiation (e.g. in tests).
    DEFAULT_ELIGIBILITY = EligibilityPolicy([ExcludeIfSeenRule(), DepsMetRule(), VariableDepsMetRule()])

    def __init__(self, dialog_id: str, moves: list[AnyMove], dependencies=None, variable_dependencies=None):
        """
        dialog_id: str, unique identifier (e.g. 'pineapple_on_pizza')
        moves: list of typed move objects representing the dialog steps
        """
        super().__init__(dialog_id, dependencies, variable_dependencies)
        self.moves = moves
        self._agent: Any = None
        self._context: RunContext | None = None

    @property
    def current_outcome(self) -> str | None:
        """The outcome set by the most recent ask-move; read by subsequent branch moves."""
        return self._context.current_outcome if self._context is not None else None

    @current_outcome.setter
    def current_outcome(self, value: str | None) -> None:
        if self._context is not None:
            self._context.current_outcome = value

    @property
    def user_model(self) -> Any:
        """The user model for the current run context."""
        return self._context.user_model if self._context is not None else {}

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
        self._context.session_history.append(entry)

    def _record_user(self, type_name: str, text: str, **extra):
        entry = {"role": "user", "type": type_name, "text": text}
        entry.update(extra)
        self._context.session_history.append(entry)

    def _record_system(self, type_name: str, text: str, **extra):
        entry = {"role": "system", "type": type_name, "text": text}
        entry.update(extra)
        self._context.session_history.append(entry)

    def _store_set_variable(self, move, answer: str):
        if not answer:
            return
        if getattr(move, "set_variable", None):
            self._context.user_model[move.set_variable] = extract_open_value(answer)

    def _store_interests(self, move, answer: str):
        if answer and getattr(move, "add_interest_from_answer", False):
            self.add_interest(self._context.topics_of_interest, answer)
        if getattr(move, "add_interest_from_variable", None):
            val = self._context.user_model.get(move.add_interest_from_variable)
            if val:
                self.add_interest(self._context.topics_of_interest, val)

    def run(self, agent: Any, context: RunContext) -> None:
        """Execute all moves in sequence using the given agent and runtime context.

        Parameters
        ----------
        agent : ConversationAgent
            Capability provider for speech, listening, and LLM calls.
        context : RunContext
            Mutable conversational state that accumulates during this run.
        """
        self._agent = agent
        self._context = context
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
            self._context.current_outcome = outcomes[answer]
        elif answer and "*" in outcomes:
            self._context.current_outcome = outcomes["*"]
        else:
            self._context.current_outcome = default_outcome

    def handle_move_branch(self, move: MoveBranch) -> None:
        """Execute the sub-moves for the case matching the current outcome or user model key."""
        key = self._context.current_outcome if move.on == "outcome" else self._context.user_model.get(move.on)
        for sub_move in move.cases.get(key, []):
            self._dispatch_move(sub_move)

    def _dispatch_move(self, move: AnyMove) -> None:
        """Route a move to its handler by naming convention: handle_move_<move.type>.

        To add a new move type, implement handle_move_<name> — no registration needed.
        Unknown move types are logged as a warning and skipped rather than raising.
        """
        handler = getattr(self, f"handle_move_{move.type}", None)
        if handler is None:
            logger.warning("No handler for move type %r — move skipped", move.type)
        else:
            handler(move)

    def _generate_llm_followup(self, user_answer: str, system_prompt: str):
        context_messages = [
            entry.get("text", "") for entry in self._context.session_history if entry.get("text") is not None
        ]
        llm_text = self._agent.ask_llm(
            user_prompt=user_answer,
            context_messages=context_messages,
            system_prompt=system_prompt,
        )
        if llm_text:
            self._agent.say(llm_text)
            self._record_robot(MOVE_LLM_FOLLOWUP, llm_text)

    def _substitute_variables(self, text: str) -> str:
        """Replace %variable% placeholders in text with values from the current user model."""
        for var, value in self._context.user_model.items():
            text = text.replace(f"%{var}%", str(value))
        return text

    def handle_move_say(self, move: MoveSay) -> None:
        text = self._substitute_variables(move.text)
        self._agent.say(text)
        self._record_robot(MOVE_SAY, text)

    def _finalize_ask(self, move, answer: str | None) -> None:
        """Shared tail for all ask-move handlers: variable storage, interests, LLM followup, and outcome resolution.

        _store_interests is safe to call for every ask type — it uses getattr with safe defaults
        and is a no-op on move types that lack add_interest_from_answer / add_interest_from_variable.
        """
        logger.debug("User answered: %s", answer)
        self._store_set_variable(move, answer)
        self._store_interests(move, answer)
        if move.llm_followup:
            self._generate_llm_followup(user_answer=answer or "", system_prompt=move.llm_followup)
        self._resolve_outcome(move, answer)

    def handle_move_ask_yesno(self, move: MoveAskYesNo) -> None:
        """Ask a yes/no question, record the answer, handle side-effects, and resolve the outcome."""
        text = self._substitute_variables(move.text)
        answer = self._agent.ask_yesno(text)
        self._record_robot(MOVE_ASK_YESNO, text)
        self._record_user(MOVE_ANSWER_YESNO, answer)
        if answer == "yes" and move.add_interest:
            self.add_interest(self._context.topics_of_interest, move.add_interest)
        self._finalize_ask(move, answer)

    def handle_move_ask_open(self, move: MoveAskOpen) -> None:
        """Ask an open-ended question, record the answer, handle side-effects, and resolve the outcome."""
        text = self._substitute_variables(move.text)
        answer = self._agent.ask_open(text)
        self._record_robot(MOVE_ASK_OPEN, text)
        self._record_user(MOVE_ANSWER_OPEN, answer)
        self._finalize_ask(move, answer)

    def handle_move_ask_options(self, move: MoveAskOptions) -> None:
        """Ask a multiple-choice question, record the answer, handle side-effects, and resolve the outcome."""
        text = self._substitute_variables(move.text)
        answer = self._agent.ask_options(text, move.options)
        self._record_robot(MOVE_ASK_OPTIONS, text, options=move.options)
        self._record_user(MOVE_ANSWER_OPTIONS, answer)
        self._finalize_ask(move, answer)

    def handle_move_play_audio(self, move: MovePlayAudio) -> None:
        self._agent.play_audio(move.audio)
        self._record_robot(MOVE_PLAY_AUDIO, "Played audio.", audio_file=move.audio)

    def handle_move_motion_sequence(self, move: MoveMotionSequence) -> None:
        self._agent.play_motion_sequence(move.motion_sequence)
        self._record_robot(MOVE_MOTION_SEQUENCE, "Played motion sequence.", motion_sequence_file=move.motion_sequence)

    def handle_move_animation(self, move: MoveAnimation) -> None:
        self._agent.play_animation(move.animation_name)
        self._record_robot(MOVE_ANIMATION, "Played animation.", animation_name=move.animation_name)

    def handle_move_ask_llm(self, move: MoveAskLLM) -> None:
        _run_llm_exchange(
            agent=self._agent,
            context=self._context,
            prompt=move.prompt,
            max_turns=move.max_turns or MAX_LLM_TURNS,
            set_variable=move.set_variable,
            quit_phrases=move.quit_phrases,
            quit_signal=move.quit_signal,
        )


class FunctionalType(Enum):
    GREETING = "greeting"
    FAREWELL = "farewell"


class FunctionalDialog(MiniDialog):
    # Indexed by the string value of functional_type (e.g. "greeting", "farewell").
    INDEX_ATTRS: list[str] = ["functional_type"]
    # No ExcludeIfSeenRule — greetings and farewells re-run at the start of every session.
    DEFAULT_ELIGIBILITY = EligibilityPolicy([DepsMetRule()])
    dialog_type: DialogType = DialogType.FUNCTIONAL

    def __init__(self, dialog_id, moves, functional_type, dependencies=None):
        # Functional dialogs are utility blocks such as greeting and farewell.
        super().__init__(dialog_id, moves, dependencies)
        # Coerce string values to the enum so comparisons work regardless of the caller's source.
        self.type = FunctionalType(functional_type) if isinstance(functional_type, str) else functional_type

    @property
    def functional_type(self) -> str:
        """String value of the functional type, used as the registry index key."""
        return self.type.value

    def is_greeting_dialog(self):
        return self.type == FunctionalType.GREETING

    def is_farewell_dialog(self):
        return self.type == FunctionalType.FAREWELL


class NarrativeDialog(MiniDialog):
    INDEX_ATTRS: list[str] = ["thread"]
    DEFAULT_ELIGIBILITY = EligibilityPolicy([ExcludeIfSeenRule(), DepsMetRule(), VariableDepsMetRule(), NarrativeOrderingRule()])
    dialog_type: DialogType = DialogType.NARRATIVE

    def __init__(self, dialog_id, moves, thread, position, dependencies=None, variable_dependencies=None):
        # Narrative dialogs belong to a thread and have an explicit position (order).
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.thread = thread
        self.position = position


class ChitchatDialog(MiniDialog):
    # topics is a list — each element is indexed individually so get_by_attr("topics", "pizza")
    # returns all ChitchatDialogs whose topics list contains "pizza".
    INDEX_ATTRS: list[str] = ["topics"]
    DEFAULT_ELIGIBILITY = EligibilityPolicy([ExcludeIfSeenRule(), DepsMetRule(), VariableDepsMetRule()])
    dialog_type: DialogType = DialogType.CHITCHAT

    def __init__(self, dialog_id, moves, topics=None, dependencies=None, variable_dependencies=None):
        # Chitchat dialogs are short interactions labelled by topics for interest-based matching.
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.topics = topics or []


class LLMDialog(BaseDialog):
    """A dialog driven entirely by a free-form multi-turn LLM conversation.

    Unlike ``MiniDialog``, ``LLMDialog`` carries no scripted move list — it
    delegates fully to ``_run_llm_exchange``. It inherits ``BaseDialog``
    directly, reflecting that it is a distinct execution strategy rather than
    a specialisation of scripted move execution.

    The ``moves`` attribute is kept (always ``[]``) for serialisation
    round-trip compatibility with the authoring layer.
    """

    INDEX_ATTRS: list[str] = []
    DEFAULT_ELIGIBILITY = EligibilityPolicy([ExcludeIfSeenRule(), DepsMetRule(), VariableDepsMetRule()])
    dialog_type: DialogType = DialogType.LLM_BASED

    def __init__(self, dialog_id, moves=None, prompt=None, max_turns=None, dependencies=None,
                 variable_dependencies=None, quit_phrases: list[str] | None = None,
                 quit_signal: str | None = None, speak_first: bool = True,
                 duration: float | None = None, rag_enabled: bool = False,
                 index_name: str | None = None):
        super().__init__(dialog_id, dependencies, variable_dependencies)
        # moves is accepted for factory round-trip compat but unused at runtime
        self.moves: List[AnyMove] = list(moves or [])
        self.prompt = prompt
        self.max_turns = max_turns  # None means use MAX_LLM_TURNS default at runtime
        self.speak_first = speak_first
        self.duration = duration
        self.rag_enabled = rag_enabled
        self.index_name = index_name
        # Quit phrases (user utterances) and quit signal (LLM-inserted token)
        self.quit_phrases = [p for p in (quit_phrases or []) if p]
        self.quit_signal = quit_signal if quit_signal is not None else "<<QUIT>>"

    def run(self, agent: Any, context: RunContext) -> None:
        """Run the LLM-driven dialog exchange."""
        _run_llm_exchange(
            agent=agent,
            context=context,
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
