from typing import Optional, List
import re

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


MAX_LLM_TURNS = 5


class MiniDialog:
    """
    Core dialog executor that processes a sequence of conversational moves.

    A MiniDialog represents a self-contained interaction flow composed of
    declarative "moves" (e.g., say, ask, branch). It manages execution,
    user state updates, and interaction history.

    Attributes:
        dialog_id (str): Unique identifier for the dialog.
        moves (list): Sequence of dialog moves (dicts or Move objects).
        dependencies (list): Dialog IDs that must be completed before this one.
        variable_dependencies (list): Required variables in the user model.

        conversation_agent: Interface used to interact with the user.
        session_history (list): Log of all interaction events.
        topics_of_interest (list): Extracted user interests.
        user_model (dict): Stored user-specific variables.
        current_outcome (str): Last resolved outcome from a move.
    """

    def __init__(self, dialog_id, moves, dependencies=None, variable_dependencies=None):
        """
        Initialize a MiniDialog.

        Args:
            dialog_id (str): Unique identifier (e.g. 'pineapple_on_pizza').
            moves (list): List of dialog moves (dicts or Move objects).
            dependencies (Optional[list]): Dialog dependencies.
            variable_dependencies (Optional[list]): Required user model variables.
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
        """
        Set runtime context for the dialog.

        Args:
            agent: Conversation agent handling I/O.
            session_history (list): Shared session history log.
            topics_of_interest (list): Shared list of user interests.
            user_model (dict): Shared user state.
        """
        self.conversation_agent = agent
        self.session_history = session_history if session_history is not None else []
        self.topics_of_interest = topics_of_interest if topics_of_interest is not None else []
        self.user_model = user_model if user_model is not None else {}

    @staticmethod
    def _get(move, key, default=None):
        """
        Safely retrieve a value from a move (dict or object).

        Args:
            move: Move dict or object.
            key (str): Attribute or dict key.
            default: Fallback value.

        Returns:
            Value associated with key or default.
        """
        try:
            if isinstance(move, dict):
                return move.get(key, default)
            return getattr(move, key, default)
        except Exception:
            return default

    @staticmethod
    def add_interest(topics_of_interest, topic):
        """
        Add a topic to the list of user interests if not already present.

        Args:
            topics_of_interest (list): List of topics.
            topic (str): Topic to add.
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
        """
        Log a robot-generated event.

        Args:
            type_name (str): Event type.
            text (str): Spoken/generated text.
            **extra: Additional metadata.
        """
        entry = {"role": "robot", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _record_user(self, type_name: str, text: str, **extra):
        """
        Log a user-generated event.
        """
        entry = {"role": "user", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _record_system(self, type_name: str, text: str, **extra):
        """
        Log a system-level event.
        """
        entry = {"role": "system", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _store_set_variable(self, move, answer: str):
        """
        Store a cleaned user answer into the user model if configured.

        Args:
            move: Move containing `set_variable`.
            answer (str): Raw user answer.
        """
        if not answer:
            return
        if getattr(move, 'set_variable', None):
            self.user_model[move.set_variable] = self.extract_open_value(answer)

    def _store_interests(self, move, answer: str):
        """
        Extract and store user interests based on move configuration.

        Args:
            move: Move configuration.
            answer (str): User answer.
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
        Extract a meaningful value from an open-ended answer.

        Heuristics:
        - Prefer quoted text.
        - Otherwise use last alphabetic token.
        - Fallback to full answer.

        Args:
            answer (str): Raw user answer.

        Returns:
            str: Extracted value.
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
        """
        Execute all moves in the dialog sequentially.

        Args:
            agent: Conversation agent.
            session_history (list): Shared session log.
            topics_of_interest (list): Shared topics list.
            user_model (dict): Shared user model.
        """
        self.set_conversation_config(agent, session_history, topics_of_interest, user_model)

        idx = 0
        while idx < len(self.moves):
            move = self.moves[idx]
            self._dispatch_move(move)
            idx += 1

    def _generate_llm_followup(self, user_answer: str, system_prompt: str):
        """
        Generate and speak a contextual LLM follow-up.

        Args:
            user_answer (str): User response.
            system_prompt (str): Prompt guiding LLM behavior.
        """
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
        """
        Execute a 'say' move with variable substitution.

        Args:
            move: Move configuration.
        """
        text = self._get(move, 'text')
        for var, value in self.user_model.items():
            text = text.replace(f"%{var}%", str(value))
        self.conversation_agent.say(text)
        self._record_robot(MOVE_SAY, text)

    def handle_move_ask_yesno(self, move):
        """
        Execute a yes/no question and process the response.

        Returns:
            str: User answer ('yes' or 'no').
        """
        move = MoveAskYesNo.from_dict(move)
        answer = self.conversation_agent.ask_yesno(move.text)
        self._record_robot(MOVE_ASK_YESNO, move.text)
        self._record_user(MOVE_ANSWER_YESNO, answer)

        self._store_set_variable(move, answer)
        if answer == "yes" and getattr(move, 'add_interest', None):
            self.add_interest(self.topics_of_interest, move.add_interest)

        if move.llm_followup:
            self._generate_llm_followup(answer or "", move.llm_followup)

        return answer

    def handle_move_ask_open(self, move):
        """
        Execute an open-ended question and process the response.

        Returns:
            str: User answer.
        """
        move = MoveAskOpen.from_dict(move)
        answer = self.conversation_agent.ask_open(move.text)
        self._record_robot(MOVE_ASK_OPEN, move.text)
        self._record_user(MOVE_ANSWER_OPEN, answer)

        self._store_set_variable(move, answer)
        self._store_interests(move, answer)

        if move.llm_followup:
            self._generate_llm_followup(answer or "", move.llm_followup)

        return answer

    def handle_move_ask_options(self, move):
        """
        Execute a multiple-choice question.

        Returns:
            str: Selected option.
        """
        move = MoveAskOptions.from_dict(move)
        answer = self.conversation_agent.ask_options(move.text, move.options)
        self._record_robot(MOVE_ASK_OPTIONS, move.text, options=move.options)
        self._record_user(MOVE_ANSWER_OPTIONS, answer)

        self._store_set_variable(move, answer)
        self._store_interests(move, answer)

        if move.llm_followup:
            self._generate_llm_followup(answer or "", move.llm_followup)

        return answer

    def _run_llm_exchange(self, prompt: str, max_turns: int, set_variable: Optional[str] = None,
                          quit_phrases: Optional[List[str]] = None, quit_signal: Optional[str] = None):
        """
        Run a multi-turn LLM-driven interaction loop.

        Args:
            prompt (str): System prompt guiding the LLM.
            max_turns (int): Maximum number of turns.
            set_variable (Optional[str]): Variable to store final answer.
            quit_phrases (Optional[list]): User phrases that end interaction.
            quit_signal (Optional[str]): LLM token that signals termination.
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
    """
    Enumeration of functional dialog types.

    These dialogs serve structural or conversational utility purposes
    rather than advancing narrative or content.

    Attributes:
        GREETING: Dialog used to greet the user at the start.
        FAREWELL: Dialog used to close the interaction.
    """
    GREETING = "greeting"
    FAREWELL = "farewell"


class FunctionalDialog(MiniDialog):
    """
    Dialog representing a functional interaction such as greeting or farewell.

    Functional dialogs are typically short, reusable building blocks that
    frame a session (e.g., opening or closing statements).

    Attributes:
        type (FunctionalType): The functional category of the dialog.
    """

    def __init__(self, dialog_id, moves, type, dependencies=None):
        """
        Initialize a FunctionalDialog.

        Args:
            dialog_id (str): Unique identifier for the dialog.
            moves (list): Sequence of dialog moves.
            type (FunctionalType): Type of functional dialog.
            dependencies (Optional[list]): Dialog dependencies.
        """
        super().__init__(dialog_id, moves, dependencies)
        self.type = type

    def is_greeting_dialog(self):
        """
        Check whether this dialog is a greeting.

        Returns:
            bool: True if dialog type is GREETING.
        """
        return self.type == FunctionalType.GREETING

    def is_farewell_dialog(self):
        """
        Check whether this dialog is a farewell.

        Returns:
            bool: True if dialog type is FAREWELL.
        """
        return self.type == FunctionalType.FAREWELL


class NarrativeDialog(MiniDialog):
    """
    Dialog representing part of a structured narrative thread.

    Narrative dialogs are ordered and grouped into threads, allowing
    multi-step storytelling or guided flows.

    Attributes:
        thread (str): Identifier for the narrative thread.
        position (int): Position of this dialog within the thread.
    """

    def __init__(self, dialog_id, moves, thread, position, dependencies=None, variable_dependencies=None):
        """
        Initialize a NarrativeDialog.

        Args:
            dialog_id (str): Unique identifier.
            moves (list): Sequence of dialog moves.
            thread (str): Narrative thread identifier.
            position (int): Order within the thread.
            dependencies (Optional[list]): Dialog dependencies.
            variable_dependencies (Optional[list]): Required variables.
        """
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.thread = thread
        self.position = position


class ChitchatDialog(MiniDialog):
    """
    Dialog representing informal, topic-driven conversation.

    Chitchat dialogs are typically short and can be selected dynamically
    based on user interests or conversation context.

    Attributes:
        theme (str): High-level theme of the dialog.
        topics (list): List of topics associated with this dialog.
    """

    def __init__(self, dialog_id, moves, theme, topics=None, dependencies=None, variable_dependencies=None):
        """
        Initialize a ChitchatDialog.

        Args:
            dialog_id (str): Unique identifier.
            moves (list): Sequence of dialog moves.
            theme (str): Theme of the conversation.
            topics (Optional[list]): Associated topics.
            dependencies (Optional[list]): Dialog dependencies.
            variable_dependencies (Optional[list]): Required variables.
        """
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.theme = theme
        self.topics = topics or []


class LLMDialog(MiniDialog):
    """
    Dialog driven primarily by a Large Language Model (LLM).

    Unlike scripted dialogs, this dialog type runs a multi-turn interaction
    loop where responses are dynamically generated by an LLM.

    Attributes:
        prompt (str): System prompt guiding the LLM behavior.
        max_turns (int): Maximum number of interaction turns.
        quit_phrases (list): User phrases that terminate the dialog early.
        quit_signal (str): Token inserted by the LLM to signal termination.
    """

    def __init__(self, dialog_id, moves, prompt, max_turns=None, dependencies=None,
                 variable_dependencies=None, quit_phrases: Optional[List[str]] = None, quit_signal: Optional[str] = None):
        """
        Initialize an LLMDialog.

        Args:
            dialog_id (str): Unique identifier.
            moves (list): Sequence of dialog moves (may be minimal or unused).
            prompt (str): System prompt for the LLM.
            max_turns (Optional[int]): Maximum number of turns.
            dependencies (Optional[list]): Dialog dependencies.
            variable_dependencies (Optional[list]): Required variables.
            quit_phrases (Optional[list]): User phrases to exit early.
            quit_signal (Optional[str]): LLM-generated termination token.
        """
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.prompt = prompt
        self.max_turns = max_turns or MAX_LLM_TURNS
        self.quit_phrases = [p for p in (quit_phrases or []) if p]
        self.quit_signal = quit_signal if quit_signal is not None else "<<QUIT>>"

    def run(self, agent, session_history, topics_of_interest, user_model):
        """
        Execute the LLM-driven dialog loop.

        This overrides the default MiniDialog execution by directly running
        a multi-turn LLM exchange instead of iterating over predefined moves.

        Args:
            agent: Conversation agent handling interaction.
            session_history (list): Shared session log.
            topics_of_interest (list): Shared topics list.
            user_model (dict): Shared user model.
        """
        self.set_conversation_config(agent, session_history, topics_of_interest, user_model)

        self._run_llm_exchange(
            prompt=self.prompt,
            max_turns=self.max_turns,
            set_variable=None,
            quit_phrases=self.quit_phrases,
            quit_signal=self.quit_signal,
        )
