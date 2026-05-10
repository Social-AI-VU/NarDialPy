from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

MOVE_SAY = "say"
MOVE_ASK_YESNO = "ask_yesno"
MOVE_ASK_OPEN = "ask_open"
MOVE_ASK_OPTIONS = "ask_options"
MOVE_ASK_LLM = "ask_llm"
MOVE_PLAY_AUDIO = "play"
MOVE_MOTION_SEQUENCE = "motion_sequence"
MOVE_ANIMATION = "animation"
MOVE_BRANCH = "branch"
MOVE_WAIT_FOR_BUTTON = "wait_for_button"
MOVE_TIMED_WAIT = "timed_wait"
MOVE_WAIT_FOR_WEB_INPUT = "wait_for_web_input"

MOVE_ANSWER_OPEN = "answer_open"
MOVE_ANSWER_YESNO = "answer_yesno"
MOVE_ANSWER_OPTIONS = "answer_options"
MOVE_ANSWER_LLM = "answer_llm"

MOVE_LLM_FOLLOWUP = "llm_followup"

LLM_QUIT_SIGNAL = "<<QUIT>>"


class MoveSay(BaseModel):
    """A move that makes the agent say a piece of text."""

    type: Literal[MOVE_SAY] = MOVE_SAY
    text: str


class MoveAskYesNo(BaseModel):
    """A move that asks a yes/no question and processes the response."""

    type: Literal[MOVE_ASK_YESNO] = MOVE_ASK_YESNO
    text: str
    set_variable: Optional[str] = None
    add_interest: Optional[str] = None
    llm_followup: Optional[str] = None
    outcomes: Dict[str, str] = Field(default_factory=dict)
    default_outcome: Optional[str] = None


class MoveAskOpen(BaseModel):
    """A move that asks an open-ended question and processes free-text input."""

    type: Literal[MOVE_ASK_OPEN] = MOVE_ASK_OPEN
    text: str
    set_variable: Optional[str] = None
    add_interest_from_answer: Optional[bool] = None
    add_interest_from_variable: Optional[str] = None
    personalize_followup: Optional[bool] = None
    llm_followup: Optional[str] = None
    outcomes: Dict[str, str] = Field(default_factory=dict)
    default_outcome: Optional[str] = None


class MoveAskOptions(BaseModel):
    """A move that asks the user to choose from a predefined set of options."""

    type: Literal[MOVE_ASK_OPTIONS] = MOVE_ASK_OPTIONS
    text: str
    options: List[str] = Field(min_length=1)
    set_variable: Optional[str] = None
    add_interest_from_variable: Optional[str] = None
    llm_followup: Optional[str] = None
    outcomes: Dict[str, str] = Field(default_factory=dict)
    default_outcome: Optional[str] = None


class MoveAskLLM(BaseModel):
    """A move that initiates a multi-turn interaction driven by a language model."""

    type: Literal[MOVE_ASK_LLM] = MOVE_ASK_LLM
    prompt: str
    set_variable: Optional[str] = None
    max_turns: Optional[int] = None
    quit_phrases: List[str] = Field(default_factory=list)
    quit_signal: str = LLM_QUIT_SIGNAL
    outcomes: Dict[str, str] = Field(default_factory=dict)
    default_outcome: Optional[str] = None


class MovePlayAudio(BaseModel):
    """A move that plays an audio file."""

    type: Literal[MOVE_PLAY_AUDIO] = MOVE_PLAY_AUDIO
    audio: str


class MoveMotionSequence(BaseModel):
    """A move that plays a predefined motion sequence on the robot."""

    type: Literal[MOVE_MOTION_SEQUENCE] = MOVE_MOTION_SEQUENCE
    motion_sequence: str


class MoveAnimation(BaseModel):
    """A move that triggers a named animation on the robot."""

    type: Literal[MOVE_ANIMATION] = MOVE_ANIMATION
    animation_name: str


class MoveBranch(BaseModel):
    """A declarative branching move that selects and executes a list of sub-moves
    based on a condition (either the current dialog outcome or a user model variable)."""

    type: Literal[MOVE_BRANCH] = MOVE_BRANCH
    on: str = "outcome"
    cases: Dict[str, List["AnyMove"]] = Field(default_factory=dict)


class MoveWaitForButton(BaseModel):
    """Suspend execution until one of the named buttons is pressed or the timeout elapses.

    Requires an active :class:`~nardial.events.bus.EventBus` in the runtime.
    When no bus is present the move resolves immediately to ``default_outcome``.

    Parameters
    ----------
    buttons : list[str]
        Accepted event source IDs (e.g. ``"chest_button"``).
    timeout : float | None
        Seconds to wait before giving up.  ``None`` means wait indefinitely.
    outcomes : dict[str, str]
        Maps source ID → outcome string when that button is pressed.
    default_outcome : str
        Outcome used on timeout or when no bus is available.
    """

    type: Literal[MOVE_WAIT_FOR_BUTTON] = MOVE_WAIT_FOR_BUTTON
    buttons: List[str]
    timeout: Optional[float] = None
    outcomes: Dict[str, str] = Field(default_factory=dict)
    default_outcome: str = "timeout"


class MoveTimedWait(BaseModel):
    """Pause dialog execution for a fixed duration.

    Parameters
    ----------
    duration_seconds : float
        How long to sleep before the next move runs.
    """

    type: Literal[MOVE_TIMED_WAIT] = MOVE_TIMED_WAIT
    duration_seconds: float


class MoveWaitForWebInput(BaseModel):
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

    type: Literal[MOVE_WAIT_FOR_WEB_INPUT] = MOVE_WAIT_FOR_WEB_INPUT
    prompt: str = ""
    options: List[str] = Field(default_factory=list)
    timeout: Optional[float] = None
    outcomes: Dict[str, str] = Field(default_factory=dict)
    default_outcome: str = "timeout"


AnyMove = Annotated[
    Union[
        MoveSay,
        MoveAskYesNo,
        MoveAskOpen,
        MoveAskOptions,
        MoveAskLLM,
        MovePlayAudio,
        MoveMotionSequence,
        MoveAnimation,
        MoveBranch,
        MoveWaitForButton,
        MoveTimedWait,
        MoveWaitForWebInput,
    ],
    Field(discriminator="type"),
]

MoveBranch.model_rebuild()
