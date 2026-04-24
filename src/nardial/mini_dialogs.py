"""Mini-dialog classes that represent the executable units of a conversation.

A *mini-dialog* is a self-contained block of dialog moves (say, ask, branch,
play audio, …) that is executed sequentially by a
:class:`~nardial.conversation_agent.ConversationAgent`.  Four specialised
subclasses cover the main dialog types used in NarDialPy:

* :class:`FunctionalDialog` – greeting / farewell utility blocks.
* :class:`NarrativeDialog` – story-driven dialog in an ordered thread.
* :class:`ChitchatDialog` – short, theme-based interactive exchanges.
* :class:`LLMDialog` – open-ended LLM-driven conversation turns.
"""

from typing import Optional, List
import re

from nardial.moves import MOVE_SAY, MOVE_ASK_YESNO, MOVE_ASK_OPEN, MOVE_ASK_OPTIONS, MOVE_PLAY_AUDIO, MOVE_MOTION_SEQUENCE, \
    MOVE_ANIMATION, \
    MoveAskYesNo, MoveAskOpen, MoveAskOptions, MovePlayAudio, MoveMotionSequence, MoveAnimation, MoveBranch, \
    MOVE_ANSWER_OPEN, MOVE_ANSWER_YESNO, MOVE_ANSWER_OPTIONS, MoveAskLLM, MOVE_ASK_LLM, MOVE_ANSWER_LLM, \
    MOVE_LLM_FOLLOWUP, MOVE_BRANCH

from enum import Enum


class DialogType(Enum):
    """Enumeration of the four dialog types supported by NarDialPy."""

    NARRATIVE = "narrative"
    CHITCHAT = "chitchat"
    FUNCTIONAL = "functional"
    LLM_BASED = "llm_based"


MAX_LLM_TURNS = 5


class MiniDialog:
    """Base class for all mini-dialogs.

    A :class:`MiniDialog` owns a list of *moves* – plain dicts or typed Move
    objects – and dispatches them one by one when :meth:`run` is called.
    Subclasses extend the initialiser to carry type-specific metadata (thread,
    theme, prompt, …).

    Args:
        dialog_id: Unique identifier for this dialog (e.g. ``"hero_dream_1"``).
        moves: Ordered list of move dicts or Move objects to execute.
        dependencies: List of dialog IDs that must have been completed before
            this dialog may run.
        variable_dependencies: List of ``{"variable": str, "required": bool}``
            dicts.  Required variables must be present and truthy in the user
            model before the dialog can run.
    """

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
        """Bind runtime conversation context before executing moves.

        Called automatically by :meth:`run`; may also be invoked explicitly
        when the same dialog instance is reused across calls.

        Args:
            agent: Active :class:`~nardial.conversation_agent.ConversationAgent`.
            session_history: Mutable list to which events are appended.
            topics_of_interest: Mutable list of topic strings gathered so far.
            user_model: Mutable dict of user-model variable values.
        """
        self.conversation_agent = agent
        self.session_history = session_history if session_history is not None else []
        self.topics_of_interest = topics_of_interest if topics_of_interest is not None else []
        self.user_model = user_model if user_model is not None else {}

    # Helper to read either dict-style or attribute-style moves (supports MoveSay objects)
    @staticmethod
    def _get(move, key, default=None):
        """Read a field from either a dict or an attribute-based Move object.

        Args:
            move: A move dict or Move object.
            key: Field name to look up.
            default: Value to return when the field is absent.

        Returns:
            The field value, or *default* if not found.
        """
        try:
            if isinstance(move, dict):
                return move.get(key, default)
            # Fallback to attribute access for move objects
            return getattr(move, key, default)
        except Exception:
            return default

    @staticmethod
    def add_interest(topics_of_interest, topic):
        """Add *topic* to *topics_of_interest* if it is not already present.

        Comparison is case-insensitive; the original casing of *topic* is kept.

        Args:
            topics_of_interest: Mutable list of existing topic strings.
            topic: New topic string to add (ignored when empty or ``None``).
        """
        if topics_of_interest is None or not topic:
            return
        t = str(topic).strip()
        if not t:
            return
        low = t.lower()
        if all(low != str(x).lower() for x in topics_of_interest):
            topics_of_interest.append(t)

    def _record_robot(self, type_name: str, text: str, **extra):
        """Append a robot-role event to the session history.

        Args:
            type_name: Move type string (e.g. ``"say"``, ``"ask_yesno"``).
            text: Text content of the event.
            **extra: Additional key/value pairs to include in the event dict.
        """
        entry = {"role": "robot", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _record_user(self, type_name: str, text: str, **extra):
        """Append a user-role event to the session history.

        Args:
            type_name: Move type string (e.g. ``"answer_yesno"``).
            text: Transcribed user reply.
            **extra: Additional key/value pairs to include in the event dict.
        """
        entry = {"role": "user", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _record_system(self, type_name: str, text: str, **extra):
        """Append a system-role event to the session history.

        Args:
            type_name: Event type string (e.g. ``"dialog_start"``).
            text: Descriptive text for the event.
            **extra: Additional key/value pairs to include in the event dict.
        """
        entry = {"role": "system", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _store_set_variable(self, move, answer: str):
        """Store *answer* in the user model under the variable named in *move*.

        Does nothing when *answer* is empty or when the move has no
        ``set_variable`` attribute.

        Args:
            move: Move object that optionally carries a ``set_variable`` name.
            answer: The user's reply to potentially store.
        """
        if not answer:
            return
        if getattr(move, 'set_variable', None):
            self.user_model[move.set_variable] = self.extract_open_value(answer)

    def _store_interests(self, move, answer: str):
        """Update ``topics_of_interest`` from the move configuration and answer.

        Reads ``add_interest_from_answer`` and ``add_interest_from_variable``
        flags on *move* and updates the running list of topics accordingly.

        Args:
            move: Move object that optionally carries interest-extraction flags.
            answer: The user's answer from which a topic may be extracted.
        """
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
        """Execute all moves in this dialog sequentially.

        Binds the conversation context, then dispatches each move in order.
        Branches are evaluated inline by :meth:`_dispatch_move`.

        Args:
            agent: Active :class:`~nardial.conversation_agent.ConversationAgent`
                used to speak and listen.
            session_history: List to which dialog events are appended.
            topics_of_interest: Running list of user interest topics.
            user_model: Dict of user-model variables.
        """
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

    def handle_move_say(self, move):
        """Handle a ``say`` move: substitute user-model variables and speak the text.

        Args:
            move: Move dict or :class:`~nardial.moves.MoveSay` object with a
                ``text`` field.
        """
        text = self._get(move, 'text')
        for var, value in self.user_model.items():
            text = text.replace(f"%{var}%", str(value))
        self.conversation_agent.say(text)
        self._record_robot(MOVE_SAY, text)

    def handle_move_ask_yesno(self, move):
        """Handle an ``ask_yesno`` move: speak the question and capture the user's response.

        Optionally stores the answer as a user-model variable, adds an
        interest topic, and generates an LLM follow-up if configured.

        Args:
            move: Move dict or :class:`~nardial.moves.MoveAskYesNo` object.

        Returns:
            ``"yes"``, ``"no"``, ``"dontknow"``, or ``None``.
        """
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
        """Handle an ``ask_open`` move: speak the question and capture a free-text answer.

        Args:
            move: Move dict or :class:`~nardial.moves.MoveAskOpen` object.

        Returns:
            The transcribed reply string, or ``None``.
        """
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
        """Handle an ``ask_options`` move: speak the question and match the reply to one of the options.

        Args:
            move: Move dict or :class:`~nardial.moves.MoveAskOptions` object.

        Returns:
            The matched option string, or ``None``.
        """
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
        """Handle a ``play`` move: play a pre-recorded audio file.

        Args:
            move: Move dict or :class:`~nardial.moves.MovePlayAudio` object
                with an ``audio`` field.
        """
        move = MovePlayAudio.from_dict(move)
        self.conversation_agent.play_audio(move.audio_file)
        self._record_robot(MOVE_PLAY_AUDIO, "Played audio. ", audio_file=move.audio_file)

    def handle_move_motion_sequence(self, move):
        """Handle a ``motion_sequence`` move: replay a recorded motion sequence.

        Args:
            move: Move dict or :class:`~nardial.moves.MoveMotionSequence`
                object with a ``motion_sequence`` field.
        """
        move = MoveMotionSequence.from_dict(move)
        self.conversation_agent.play_motion_sequence(move.sequence_file)
        self._record_robot(MOVE_MOTION_SEQUENCE, "Played motion sequence.", motion_sequence_file=move.sequence_file)

    def handle_move_animation(self, move):
        """Handle an ``animation`` move: play a named NaoQi or Alphamini animation.

        Args:
            move: Move dict or :class:`~nardial.moves.MoveAnimation` object
                with an ``animation_name`` field.
        """
        move = MoveAnimation.from_dict(move)
        self.conversation_agent.play_animation(move.animation_name)
        self._record_robot(MOVE_ANIMATION, "Played animation. ", animation_name=move.animation_name)

    def handle_move_ask_llm(self, move):
        """Handle an ``ask_llm`` move: run an LLM-driven multi-turn exchange.

        Args:
            move: Move dict or :class:`~nardial.moves.MoveAskLLM` object.
        """
        move = MoveAskLLM.from_dict(move)
        self._run_llm_exchange(
            prompt=move.prompt,
            max_turns=move.max_turns or MAX_LLM_TURNS,
            set_variable=move.set_variable,
            quit_phrases=move.quit_phrases,
            quit_signal=move.quit_signal,
        )

    def _run_llm_exchange(self, prompt: str, max_turns: int, set_variable: Optional[str] = None,
                          quit_phrases: Optional[List[str]] = None, quit_signal: Optional[str] = None):
        """Drive a multi-turn conversation using the LLM.

        The LLM speaks first (prompted by *prompt*), then listens for a user
        reply, and continues for up to *max_turns* cycles.  The loop
        terminates early if the LLM embeds *quit_signal* in its output or if
        the user says one of the *quit_phrases*.

        Args:
            prompt: System prompt that instructs the LLM how to converse.
            max_turns: Maximum number of back-and-forth exchanges.
            set_variable: Optional user-model variable name in which to store
                the last user reply.
            quit_phrases: User utterances that immediately end the exchange.
            quit_signal: Token that the LLM may embed to signal it wants to
                end the exchange.
        """
        dialog_history = []
        user_input = ""
        for _ in range(max_turns or MAX_LLM_TURNS):
            llm_text = self.conversation_agent.ask_llm(user_prompt=user_input, context_messages=dialog_history, system_prompt=prompt)
            if llm_text is None:
                continue

            # If the LLM embeds a quit signal, speak any remaining content and stop
            if quit_signal and quit_signal in llm_text:
                clean = llm_text.replace(quit_signal, "").strip()
                if clean:
                    self.conversation_agent.say(clean)
                    self._record_robot(MOVE_SAY, clean)
                return

            # Ask the user the LLM's text and listen for reply
            user_input = self.conversation_agent.ask_open(llm_text)
            if not user_input:
                user_input = ""

            # Record the exchange using the provided record types
            self._record_robot(MOVE_ASK_LLM, llm_text)
            self._record_user(MOVE_ANSWER_LLM, user_input)

            # Optionally store a variable from user's answer
            if set_variable and user_input:
                self.user_model[set_variable] = self.extract_open_value(user_input)

            # If the user said a configured quit phrase, stop early
            quit_happened = False
            for qp in (quit_phrases or []):
                if not qp:
                    continue
                if qp.lower() in user_input.lower():
                    quit_happened = True
                    break
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
                 variable_dependencies=None, quit_phrases: Optional[List[str]] = None, quit_signal: Optional[str] = None):
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.prompt = prompt
        self.max_turns = max_turns or MAX_LLM_TURNS
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
        )
