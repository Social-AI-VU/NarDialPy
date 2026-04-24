from typing import Optional, List
import re

from nardial.moves import MOVE_SAY, MOVE_ASK_YESNO, MOVE_ASK_OPEN, MOVE_ASK_OPTIONS, MOVE_PLAY_AUDIO, MOVE_MOTION_SEQUENCE, \
    MOVE_ANIMATION, \
    MoveAskYesNo, MoveAskOpen, MoveAskOptions, MovePlayAudio, MoveMotionSequence, MoveAnimation, MoveBranch, \
    MOVE_ANSWER_OPEN, MOVE_ANSWER_YESNO, MOVE_ANSWER_OPTIONS, MoveAskLLM, MOVE_ASK_LLM, MOVE_ANSWER_LLM, \
    MOVE_LLM_FOLLOWUP, MOVE_BRANCH

from enum import Enum

MAX_LLM_TURNS = 5


class DialogType(Enum):
    """
    Enumeration of supported dialog categories.
    """
    NARRATIVE = "narrative"
    CHITCHAT = "chitchat"
    FUNCTIONAL = "functional"
    LLM_BASED = "llm_based"


class MiniDialog:
    """
    Base class representing a modular dialog composed of sequential moves.

    A MiniDialog executes a list of moves using a conversation agent,
    while maintaining session history, user model, and outcomes.
    """

    def __init__(self, dialog_id, moves, dependencies=None, variable_dependencies=None):
        """
        Initialize a MiniDialog.

        Args:
            dialog_id (str): Unique identifier for the dialog.
            moves (list): List of dialog moves (dicts or move objects).
            dependencies (list, optional): Dialog dependencies.
            variable_dependencies (list, optional): Required user variables.
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
        Configure runtime context for the dialog.

        Args:
            agent: Conversation agent instance.
            session_history (list): Previous interaction history.
            topics_of_interest (list): Known user interests.
            user_model (dict): Stored user variables.
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
            move: Move object or dictionary.
            key (str): Key or attribute name.
            default: Default value if not found.

        Returns:
            Any: Retrieved value or default.
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
        Add a topic to the interest list if not already present.

        Args:
            topics_of_interest (list): List of interests.
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
        Log a robot-generated message.

        Args:
            type_name (str): Move type identifier.
            text (str): Message content.
            **extra: Additional metadata.
        """
        entry = {"role": "robot", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _record_user(self, type_name: str, text: str, **extra):
        """
        Log a user message.

        Args:
            type_name (str): Move type identifier.
            text (str): Message content.
            **extra: Additional metadata.
        """
        entry = {"role": "user", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _record_system(self, type_name: str, text: str, **extra):
        """
        Log a system-level message.

        Args:
            type_name (str): Message type.
            text (str): Message content.
            **extra: Additional metadata.
        """
        entry = {"role": "system", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _store_set_variable(self, move, answer: str):
        """
        Store an extracted value from a user answer into the user model.

        Args:
            move: Move definition.
            answer (str): User response.
        """
        if not answer:
            return
        if getattr(move, 'set_variable', None):
            self.user_model[move.set_variable] = self.extract_open_value(answer)

    def _store_interests(self, move, answer: str):
        """
        Extract and store user interests based on a move configuration.

        Args:
            move: Move definition.
            answer (str): User response.
        """
        if answer and getattr(move, 'add_interest_from_answer', False):
            self.add_interest(self.topics_of_interest, answer)
        if getattr(move, 'add_interest_from_variable', None):
            val = self.user_model.get(move.add_interest_from_variable)
            if val:
                self.add_interest(self.topics_of_interest, val)

    def run(self, agent, session_history=None, topics_of_interest=None, user_model=None):
        """
        Execute all dialog moves sequentially.

        Args:
            agent: Conversation agent.
            session_history (list, optional): Existing history.
            topics_of_interest (list, optional): Interest list.
            user_model (dict, optional): User state.
        """
        self.set_conversation_config(agent, session_history, topics_of_interest, user_model)

        idx = 0
        while idx < len(self.moves):
            move = self.moves[idx]
            self._dispatch_move(move)
            idx += 1

    def _resolve_outcome(self, move, answer) -> None:
        """
        Determine and store the outcome of a move based on the answer.

        Resolution priority:
        1. Exact match
        2. Wildcard "*"
        3. Default outcome

        Args:
            move: Move definition.
            answer (str): User response.
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
        """
        Execute a conditional branch based on outcome or user variable.

        Args:
            move: Branch move definition.
        """
        move = MoveBranch.from_dict(move)
        if move.on == "outcome":
            key = self.current_outcome
        else:
            key = self.user_model.get(move.on)
        case_moves = move.cases.get(key, [])
        for sub_move in case_moves:
            self._dispatch_move(sub_move)

    def _dispatch_move(self, move) -> None:
        """
        Route a move to its corresponding handler.

        Args:
            move: Move definition.
        """
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
        """
        Generate and speak an LLM-based follow-up response.

        Args:
            user_answer (str): User input.
            system_prompt (str): Prompt guiding the LLM response.
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


class FunctionalType(Enum):
    GREETING = "greeting"
    FAREWELL = "farewell"


class FunctionalDialog(MiniDialog):
    """
        Dialog used for functional interactions such as greetings or farewells.
    """
    def __init__(self, dialog_id, moves, type, dependencies=None):
        # Functional dialogs are utility blocks such as greeting and farewell.
        super().__init__(dialog_id, moves, dependencies)
        self.type = type

    def is_greeting_dialog(self):
        return self.type == FunctionalType.GREETING

    def is_farewell_dialog(self):
        return self.type == FunctionalType.FAREWELL


class NarrativeDialog(MiniDialog):
    """
        Dialog that belongs to a narrative thread with an ordered position.
    """
    def __init__(self, dialog_id, moves, thread, position, dependencies=None, variable_dependencies=None):
        # Narrative dialogs belong to a thread and have an explicit position (order).
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.thread = thread
        self.position = position


class ChitchatDialog(MiniDialog):
    """
        Dialog for informal, theme-based conversations.
    """
    def __init__(self, dialog_id, moves, theme, topics=None, dependencies=None, variable_dependencies=None):
        # Chitchat dialogs are short, theme-based interactions that can be biased by topics.
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.theme = theme
        self.topics = topics or []


class LLMDialog(MiniDialog):
    """
        Dialog fully driven by an LLM with multi-turn interaction support.
    """
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
