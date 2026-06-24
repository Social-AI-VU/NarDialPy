from typing import Optional
from typing import Dict, List
from abc import abstractmethod

MOVE_SAY = "say"
MOVE_SAY_OPTIONS = "say_options"
MOVE_ASK_YESNO = "ask_yesno"
MOVE_ASK_OPEN = "ask_open"
MOVE_ASK_OPTIONS = "ask_options"
MOVE_ASK_LLM = "ask_llm"
MOVE_PLAY_AUDIO = "play"
MOVE_MOTION_SEQUENCE = "motion_sequence"
MOVE_ANIMATION = "animation"
MOVE_BRANCH = "branch"

MOVE_TIMED_WAIT = "timed_wait"
MOVE_WAIT_FOR_WEB_INPUT = "wait_for_web_input"
MOVE_SHOW_IMAGE = "show_image"
MOVE_SHOW_VIDEO = "show_video"
MOVE_SHOW_IFRAME = "show_iframe"
MOVE_SHOW_HTML = "show_html"
MOVE_BLACK_SCREEN = "black_screen"

MOVE_ANSWER_OPEN = "answer_open"
MOVE_ANSWER_YESNO = "answer_yesno"
MOVE_ANSWER_OPTIONS = "answer_options"
MOVE_ANSWER_LLM = "answer_llm"

MOVE_LLM_FOLLOWUP = "llm_followup"

LLM_QUIT_SIGNAL = "<<QUIT>>"


class Move:
    """
    Abstract base class for all dialog moves.

    A move represents a single step in a dialog flow (e.g., saying something,
    asking a question, playing audio, or branching logic).
    """

    def __init__(self):
        pass

    @abstractmethod
    def get_type(self):
        """
        Return the type identifier of the move.

        :return: A string constant representing the move type.
        """
        pass


class MoveSay(Move):
    """
    A move that makes the agent say a piece of text.
    """

    def __init__(self, text: str):
        """
        :param text: The text the agent should speak.
        """
        super().__init__()
        self.type = MOVE_SAY
        self.text = text

    def get_type(self):
        """Return the move type."""
        return self.type


class MoveAskYesNo(Move):
    """
    A move that asks a yes/no question and processes the response.
    """

    def __init__(self, text: str, set_variable: Optional[str] = None,
                 add_interest: Optional[str] = None, llm_followup: Optional[str] = None,
                 outcomes: Optional[Dict[str, str]] = None, default_outcome: Optional[str] = None):
        """
        :param text: Question text to ask the user.
        :param set_variable: Optional user model variable to store the answer.
        :param add_interest: Topic to add if the user answers "yes".
        :param llm_followup: Optional system prompt for generating an LLM follow-up.
        :param outcomes: Mapping from answers to outcome labels.
        :param default_outcome: Fallback outcome label if no match is found.
        """
        super().__init__()
        self.type = MOVE_ASK_YESNO
        self.text = text
        self.set_variable = set_variable
        self.add_interest = add_interest
        self.outcomes = dict(outcomes or {})
        self.default_outcome = default_outcome
        self.llm_followup = llm_followup

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """
        Create a MoveAskYesNo instance from a dictionary.

        :param data: Dictionary representation of the move.
        :return: MoveAskYesNo instance.
        """
        return cls(
            text=data.get("text"),
            set_variable=data.get("set_variable"),
            add_interest=data.get("add_interest"),
            outcomes=data.get("outcomes"),
            default_outcome=data.get("default_outcome"),
            llm_followup=data.get("llm_followup"),
        )


class MoveAskOpen(Move):
    """
    A move that asks an open-ended question and processes free-text input.
    """

    def __init__(self, text: str, set_variable: Optional[str] = None,
                 add_interest_from_answer: Optional[bool] = None,
                 add_interest_from_variable: Optional[str] = None,
                 personalize_followup: Optional[bool] = None,
                 outcomes: Optional[Dict[str, str]] = None, default_outcome: Optional[str] = None,
                 llm_followup: Optional[str] = None):
        """
        :param text: Question text to ask the user.
        :param set_variable: Variable name to store extracted answer value.
        :param add_interest_from_answer: Whether to add answer as a topic of interest.
        :param add_interest_from_variable: Variable whose value should be added as interest.
        :param personalize_followup: Whether to personalize follow-up behavior.
        :param outcomes: Mapping from answers to outcome labels.
        :param default_outcome: Fallback outcome label.
        :param llm_followup: Optional LLM follow-up system prompt.
        """
        super().__init__()
        self.type = MOVE_ASK_OPEN
        self.text = text
        self.set_variable = set_variable
        self.add_interest_from_answer = add_interest_from_answer
        self.add_interest_from_variable = add_interest_from_variable
        self.personalize_followup = personalize_followup
        self.outcomes = dict(outcomes or {})
        self.default_outcome = default_outcome
        self.llm_followup = llm_followup

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """
        Create a MoveAskOpen instance from a dictionary.

        :param data: Dictionary representation of the move.
        :return: MoveAskOpen instance.
        """
        return cls(
            text=data.get("text"),
            set_variable=data.get("set_variable"),
            add_interest_from_variable=data.get("add_interest_from_variable"),
            add_interest_from_answer=data.get("add_interest_from_answer"),
            personalize_followup=data.get("personalize_followup"),
            outcomes=data.get("outcomes"),
            default_outcome=data.get("default_outcome"),
            llm_followup=data.get("llm_followup"),
        )


class MoveAskOptions(Move):
    """
    A move that asks the user to choose from a predefined set of options.
    """

    def __init__(self, text: str, options: List[str], set_variable: Optional[str] = None,
                 add_interest_from_variable: Optional[str] = None, llm_followup: Optional[str] = None,
                 outcomes: Optional[Dict[str, str]] = None, default_outcome: Optional[str] = None):
        """
        :param text: Question text to present to the user.
        :param options: List of selectable options.
        :param set_variable: Variable to store selected option.
        :param add_interest_from_variable: Variable whose value is added as interest.
        :param llm_followup: Optional LLM follow-up system prompt.
        :param outcomes: Mapping from answers to outcome labels.
        :param default_outcome: Fallback outcome label.
        """
        super().__init__()
        self.type = MOVE_ASK_OPTIONS
        self.text = text
        self.options = options or []
        self.set_variable = set_variable
        self.add_interest_from_variable = add_interest_from_variable
        self.outcomes = dict(outcomes or {})
        self.default_outcome = default_outcome
        self.llm_followup = llm_followup

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """
        Create a MoveAskOptions instance from a dictionary.

        :param data: Dictionary representation of the move.
        :return: MoveAskOptions instance.
        """
        return cls(
            text=data.get("text"),
            options=data.get("options"),
            set_variable=data.get("set_variable"),
            add_interest_from_variable=data.get("add_interest_from_variable"),
            outcomes=data.get("outcomes"),
            default_outcome=data.get("default_outcome"),
            llm_followup=data.get("llm_followup"),
        )


class MoveAskLLM(Move):
    """
    A move that initiates a multi-turn interaction driven by a language model.
    """

    def __init__(self, prompt: str, set_variable: Optional[str] = None,
                 max_turns: Optional[int] = None, quit_phrases: Optional[List[str]] = None,
                 quit_signal: Optional[str] = None,
                 outcomes: Optional[Dict[str, str]] = None, default_outcome: Optional[str] = None):
        """
        :param prompt: System prompt guiding the LLM interaction.
        :param set_variable: Variable to store extracted user input.
        :param max_turns: Maximum number of back-and-forth turns.
        :param quit_phrases: User phrases that terminate the interaction.
        :param quit_signal: Token the LLM can emit to signal termination.
        :param outcomes: Mapping from answers to outcome labels.
        :param default_outcome: Fallback outcome label.
        """
        super().__init__()
        self.type = MOVE_ASK_LLM
        self.prompt = prompt
        self.set_variable = set_variable
        self.max_turns = max_turns
        self.quit_phrases = [p for p in (quit_phrases or []) if p]
        self.quit_signal = quit_signal if quit_signal is not None else LLM_QUIT_SIGNAL
        self.outcomes = dict(outcomes or {})
        self.default_outcome = default_outcome

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """
        Create a MoveAskLLM instance from a dictionary.

        :param data: Dictionary representation of the move.
        :return: MoveAskLLM instance.
        """
        return cls(
            prompt=data.get("prompt"),
            set_variable=data.get("set_variable"),
            max_turns=data.get("max_turns"),
            quit_phrases=data.get("quit_phrases"),
            quit_signal=data.get("quit_signal"),
            outcomes=data.get("outcomes"),
            default_outcome=data.get("default_outcome"),
        )


class MovePlayAudio(Move):
    """
    A move that plays an audio file.
    """

    def __init__(self, audio_file: str):
        """
        :param audio_file: Path to the audio file to play.
        """
        super().__init__()
        self.type = MOVE_PLAY_AUDIO
        self.audio_file = audio_file

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """
        Create a MovePlayAudio instance from a dictionary.

        :param data: Dictionary containing audio file path.
        :return: MovePlayAudio instance.
        """
        return cls(
            audio_file=data.get("audio"),
        )


class MoveMotionSequence(Move):
    """
    A move that plays a predefined motion sequence on the robot.
    """

    def __init__(self, sequence_file: str):
        """
        :param sequence_file: Path to the motion sequence file.
        """
        super().__init__()
        self.type = MOVE_MOTION_SEQUENCE
        self.sequence_file = sequence_file

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """
        Create a MoveMotionSequence instance from a dictionary.

        :param data: Dictionary containing motion sequence file path.
        :return: MoveMotionSequence instance.
        """
        return cls(
            sequence_file=data.get("motion_sequence"),
        )


class MoveAnimation(Move):
    """
    A move that triggers a named animation on the robot.
    """

    def __init__(self, animation_name: str):
        """
        :param animation_name: Name of the animation to play.
        """
        super().__init__()
        self.type = MOVE_ANIMATION
        self.animation_name = animation_name

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """
        Create a MoveAnimation instance from a dictionary.

        :param data: Dictionary containing animation name.
        :return: MoveAnimation instance.
        """
        return cls(
            animation_name=data.get("animation_name"),
        )


class MoveBranch(Move):
    """
    A declarative branching move that selects and executes a list of sub-moves
    based on a condition (either the current dialog outcome or a user model variable).
    """

    def __init__(self, on: str, cases: Optional[Dict[str, List]] = None):
        """
        :param on: Source of branching condition ("outcome" or variable name).
        :param cases: Mapping from condition values to lists of sub-moves.
        """
        super().__init__()
        self.type = MOVE_BRANCH
        self.on = on or "outcome"
        self.cases = dict(cases or {})

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """
        Create a MoveBranch instance from a dictionary.

        :param data: Dictionary containing branching configuration.
        :return: MoveBranch instance.
        """
        return cls(
            on=data.get("on", "outcome"),
            cases=data.get("cases", {}),
        )


class MoveTimedWait(Move):
    """Pause dialog execution for a fixed duration.

    Parameters
    ----------
    duration_seconds : float
        How long to sleep before the next move runs.
    """

    def __init__(self, duration_seconds: float):
        super().__init__()
        self.type = MOVE_TIMED_WAIT
        self.duration_seconds = duration_seconds

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """Create a MoveTimedWait instance from a dictionary."""
        return cls(
            duration_seconds=data.get("duration_seconds") or data.get("duration") or 0,
        )


class MoveWaitForWebInput(Move):
    """Suspend execution until a web input event arrives or the timeout elapses.

    The move listens on the event bus for ``web_input`` events whose
    ``data["value"]`` is in ``options``.  Requires an active
    :class:`~nardial.events.bus.EventBus`.  Resolves to ``default_outcome``
    when no bus is available or on timeout.

    Parameters
    ----------
    prompt : str
        Hint text for the web UI (not spoken by the robot).
    options : list[str]
        Accepted ``value`` strings from the web input event.
    timeout : float | None
        Seconds to wait.  ``None`` means wait indefinitely.
    outcomes : dict[str, str]
        Maps option value → outcome string.
    default_outcome : str
        Outcome used on timeout or when no bus is available.
    """

    def __init__(self, prompt: Optional[str] = None, options: Optional[List[str]] = None,
                 timeout: Optional[float] = None, outcomes: Optional[Dict[str, str]] = None,
                 default_outcome: Optional[str] = None):
        super().__init__()
        self.type = MOVE_WAIT_FOR_WEB_INPUT
        self.prompt = prompt or ""
        # store options as list of strings
        self.options = list(options or [])
        self.timeout = timeout
        self.outcomes = dict(outcomes or {})
        self.default_outcome = default_outcome

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """Create a MoveWaitForWebInput from a dictionary."""
        return cls(
            prompt=data.get("prompt"),
            options=data.get("options"),
            timeout=data.get("timeout"),
            outcomes=data.get("outcomes"),
            default_outcome=data.get("default_outcome"),
        )


class MoveShowImage(Move):
    """Display an image on the connected screen.

    Parameters
    ----------
    src : str
        Local file path (relative to the static directory) or a full URL.
    """

    def __init__(self, src: str):
        super().__init__()
        self.type = MOVE_SHOW_IMAGE
        self.src = src

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """Create a MoveShowImage instance from a dictionary."""
        return cls(
            src=data.get("src") or data.get("image") or data.get("path"),
        )


class MoveShowVideo(Move):
    """Display a video on the connected screen.

    Parameters
    ----------
    src : str
        Local file path or an embeddable URL (e.g. a YouTube embed URL).
    """

    def __init__(self, src: str):
        super().__init__()
        self.type = MOVE_SHOW_VIDEO
        self.src = src

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """Create a MoveShowVideo instance from a dictionary."""
        return cls(
            src=data.get("src") or data.get("video") or data.get("path"),
        )


class MoveShowIframe(Move):
    """Embed an external URL in an iframe on the screen.

    Parameters
    ----------
    url : str
        The URL to embed.
    """

    def __init__(self, url: str):
        super().__init__()
        self.type = MOVE_SHOW_IFRAME
        self.url = url

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """Create a MoveShowIframe instance from a dictionary."""
        return cls(
            url=data.get("url") or data.get("src") or data.get("iframe_url"),
        )


class MoveShowHtml(Move):
    """Render a raw HTML snippet in the display area.

    Parameters
    ----------
    html : str
        The HTML to inject.  Dialog authors are responsible for keeping this
        trusted; the frontend renders it verbatim via ``innerHTML``.
    """

    def __init__(self, html: str):
        super().__init__()
        self.type = MOVE_SHOW_HTML
        self.html = html

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """Create a MoveShowHtml instance from a dictionary."""
        return cls(
            html=data.get("html"),
        )


class MoveBlackScreen(Move):
    """Set the display to black/blank — no content shown.

    No parameters.  The next display move will restore content.
    """

    def __init__(self):
        super().__init__()
        self.type = MOVE_BLACK_SCREEN

    def get_type(self):
        """Return the move type."""
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        """Create a MoveBlackScreen instance from a dictionary (no params)."""
        return cls()
