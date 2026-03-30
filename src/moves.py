from typing import Optional
from typing import Dict, List
from abc import abstractmethod

MOVE_SAY = "say"
MOVE_ASK_YESNO = "ask_yesno"
MOVE_ASK_OPEN = "ask_open"
MOVE_ASK_OPTIONS = "ask_options"
MOVE_ASK_LLM = "ask_llm"
MOVE_PLAY_AUDIO = "play"
MOVE_MOTION_SEQUENCE = "motion_sequence"
MOVE_ANIMATION = "animation"

MOVE_ANSWER_OPEN = "answer_open"
MOVE_ANSWER_YESNO = "answer_yesno"
MOVE_ANSWER_OPTIONS = "answer_options"
MOVE_ANSWER_LLM = "answer_llm"

LLM_QUIT_SIGNAL = "<<QUIT>>"

class Move:
    """Abstract base class for all dialog moves."""

    def __init__(self):
        pass

    @abstractmethod
    def get_type(self):
        """Return the move-type string constant (e.g. ``"say"``, ``"ask_yesno"``)."""
        pass


class MoveSay(Move):
    """A move that makes the robot say a piece of text."""

    def __init__(self, text: str):
        super().__init__()
        self.type = MOVE_SAY
        self.text = text

    def get_type(self):
        return self.type


class MoveAskYesNo(Move):
    """A move that asks a yes/no question and optionally records the answer.

    Args:
        text: The question to ask.
        next_map: Mapping ``{"success": "<branch>", "fail": "<branch>"}`` that
            controls which dialog branch to follow depending on the answer.
        set_variable: If provided, store the user's answer in
            ``user_model[set_variable]``.
        add_interest: Topic string to add to ``topics_of_interest`` when the
            user answers ``"yes"``.
        branch: Execute this move only when the active branch label matches.
    """

    def __init__(self, text: str, next_map: Optional[Dict[str, str]] = None,
                 set_variable: Optional[str] = None, add_interest: Optional[str] = None, branch: Optional[str] = None):
        super().__init__()
        self.type = MOVE_ASK_YESNO
        self.text = text
        # Engine reads 'next'; we also keep 'next_map' as an alias for convenience
        self.next = dict(next_map or {})
        self.next_map = self.next
        self.set_variable = set_variable
        self.add_interest = add_interest
        self.branch = branch

    def get_type(self):
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """Construct a :class:`MoveAskYesNo` from a raw move dictionary."""
        return cls(
            text=data.get("text"),
            next_map=data.get("next"),
            set_variable=data.get("set_variable"),
            add_interest=data.get("add_interest"),
            branch=data.get("branch"),
        )


class MoveAskOpen(Move):
    """A move that asks an open-ended question and captures the user's reply.

    Args:
        text: The question to ask.
        next_map: Branch map ``{"success": "...", "fail": "..."}``.
        set_variable: Store an extracted keyword from the answer in
            ``user_model[set_variable]``.
        add_interest_from_answer: When ``True``, add the answer to
            ``topics_of_interest``.
        add_interest_from_variable: Add the value stored under this
            ``user_model`` key to ``topics_of_interest``.
        branch: Conditional execution branch label.
        personalize_followup: When ``True``, generate a GPT-powered follow-up
            line using the user's age and answer.
    """

    def __init__(self, text: str, next_map: Optional[Dict[str, str]] = None,
                 set_variable: Optional[str] = None, add_interest_from_answer: Optional[bool] = None,
                 add_interest_from_variable: Optional[str] = None, branch: Optional[str] = None,
                 personalize_followup: Optional[bool] = None):
        super().__init__()
        self.type = MOVE_ASK_OPEN
        self.text = text
        # Engine reads 'next'; keep 'next_map' as alias for convenience
        self.next = dict(next_map or {})
        self.next_map = self.next
        self.set_variable = set_variable
        self.add_interest_from_answer = add_interest_from_answer
        self.add_interest_from_variable = add_interest_from_variable
        self.branch = branch
        self.personalize_followup = personalize_followup

    def get_type(self):
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """Construct a :class:`MoveAskOpen` from a raw move dictionary."""
        return cls(
            text=data.get("text"),
            next_map=data.get("next"),
            set_variable=data.get("set_variable"),
            add_interest_from_variable=data.get("add_interest_from_variable"),
            add_interest_from_answer=data.get("add_interest_from_answer"),
            branch=data.get("branch"),
            personalize_followup=data.get("personalize_followup"),
        )


class MoveAskOptions(Move):
    """A move that presents a list of options and asks the user to choose one.

    Args:
        text: The question to ask.
        options: List of option strings the user may choose from.
        next_map: Branch map ``{"success": "...", "fail": "..."}``.
        set_variable: Store the chosen option in ``user_model[set_variable]``.
        add_interest_from_variable: Add the value stored under this
            ``user_model`` key to ``topics_of_interest``.
        branch: Conditional execution branch label.
    """

    def __init__(self, text: str, options: List[str], next_map: Optional[Dict[str, str]] = None,
                 set_variable: Optional[str] = None,
                 add_interest_from_variable: Optional[str] = None, branch: Optional[str] = None):
        super().__init__()
        self.type = MOVE_ASK_OPTIONS
        self.text = text
        self.options = options or []
        # Engine reads 'next'; keep 'next_map' as alias for convenience
        self.next = dict(next_map or {})
        self.next_map = self.next
        self.set_variable = set_variable
        self.add_interest_from_variable = add_interest_from_variable
        self.branch = branch

    def get_type(self):
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """Construct a :class:`MoveAskOptions` from a raw move dictionary."""
        return cls(
            text=data.get("text"),
            options=data.get("options"),
            next_map=data.get("next"),
            set_variable=data.get("set_variable"),
            add_interest_from_variable=data.get("add_interest_from_variable"),
            branch=data.get("branch")
        )


class MoveAskLLM(Move):
    """A move that drives an open-ended LLM-based conversation exchange.

    The robot repeatedly queries the LLM and asks the user for a response until
    ``max_turns`` is reached, the user says a quit phrase, or the LLM embeds the
    ``quit_signal`` token.

    Args:
        prompt: System prompt passed to the LLM for every turn.
        next_map: Branch map (currently unused by the runtime, reserved for
            future use).
        set_variable: Store a keyword extracted from the last user answer in
            ``user_model[set_variable]``.
        branch: Conditional execution branch label.
        max_turns: Maximum number of back-and-forth turns (default: 5).
        quit_phrases: User utterances (case-insensitive substrings) that end
            the exchange early.
        quit_signal: Token the LLM can embed in its response to signal that the
            conversation should end (default: ``"<<QUIT>>"``).
    """

    def __init__(self, prompt: str, next_map: Optional[Dict[str, str]] = None,
                 set_variable: Optional[str] = None, branch: Optional[str] = None,
                 max_turns: Optional[int] = None, quit_phrases: Optional[List[str]] = None, quit_signal: Optional[str] = None):
        super().__init__()
        self.type = MOVE_ASK_LLM
        self.prompt = prompt
        # Engine reads 'next'; keep 'next_map' as alias for convenience
        self.next = dict(next_map or {})
        self.next_map = self.next
        self.set_variable = set_variable
        self.branch = branch
        # Max turns limits the number of back-and-forth exchanges with the LLM for this move
        self.max_turns = max_turns
        # Quit phrases are user utterances that should end the LLM-driven exchange
        self.quit_phrases = [p for p in (quit_phrases or []) if p]
        # Quit signal is an optional token that the LLM can include in its response to signal termination
        self.quit_signal = quit_signal if quit_signal is not None else LLM_QUIT_SIGNAL

    def get_type(self):
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """Construct a :class:`MoveAskLLM` from a raw move dictionary."""
        return cls(
            prompt=data.get("prompt"),
            next_map=data.get("next"),
            set_variable=data.get("set_variable"),
            branch=data.get("branch"),
            max_turns=data.get("max_turns"),
            quit_phrases=data.get("quit_phrases"),
            quit_signal=data.get("quit_signal"),
        )


class MovePlayAudio(Move):
    """A move that plays a 16-bit WAV audio file through the device speaker.

    Args:
        audio_file: Path to the WAV file to play.
    """

    def __init__(self, audio_file: str):
        super().__init__()
        self.type = MOVE_PLAY_AUDIO
        self.audio_file = audio_file

    def get_type(self):
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """Construct a :class:`MovePlayAudio` from a raw move dictionary."""
        return cls(
            audio_file=data.get("audio"),
        )


class MoveMotionSequence(Move):
    """A move that replays a recorded NAO/Pepper motion sequence.

    Silently skipped when running on a Desktop device.

    Args:
        sequence_file: Path to the recorded motion sequence file.
    """

    def __init__(self, sequence_file: str):
        super().__init__()
        self.type = MOVE_MOTION_SEQUENCE
        self.sequence_file = sequence_file

    def get_type(self):
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """Construct a :class:`MoveMotionSequence` from a raw move dictionary."""
        return cls(
            sequence_file=data.get("motion_sequence"),
        )


class MoveAnimation(Move):
    """A move that triggers a named built-in NAO/Pepper animation.

    Silently skipped when running on a Desktop device.

    Args:
        animation_name: The built-in animation identifier
            (e.g. ``"animations/Stand/Gestures/Yes_1"``).
    """

    def __init__(self, animation_name: str):
        super().__init__()
        self.type = MOVE_ANIMATION
        self.animation_name = animation_name

    def get_type(self):
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """Construct a :class:`MoveAnimation` from a raw move dictionary."""
        return cls(
            animation_name=data.get("animation_name"),
        )


