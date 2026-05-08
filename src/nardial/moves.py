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
    ],
    Field(discriminator="type"),
]

MoveBranch.model_rebuild()
