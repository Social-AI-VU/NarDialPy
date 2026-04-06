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

MOVE_RESPONSE_LLM = "response_llm"

LLM_QUIT_SIGNAL = "<<QUIT>>"

class Move:
    def __init__(self):
        pass

    @abstractmethod
    def get_type(self):
        pass


class MoveSay(Move):
    def __init__(self, text: str):
        super().__init__()
        self.type = MOVE_SAY
        self.text = text

    def get_type(self):
        return self.type


class MoveAskYesNo(Move):
    def __init__(self, text: str, next_map: Optional[Dict[str, str]] = None,
                 set_variable: Optional[str] = None, add_interest: Optional[str] = None, branch: Optional[str] = None,
                 llm_followup: Optional[str] = None):
        super().__init__()
        self.type = MOVE_ASK_YESNO
        self.text = text
        # Engine reads 'next'; we also keep 'next_map' as an alias for convenience
        self.next = dict(next_map or {})
        self.next_map = self.next
        self.set_variable = set_variable
        self.add_interest = add_interest
        self.branch = branch
        # Optional LLM-generated followup: system prompt string, generated after the user replies
        self.llm_followup = llm_followup

    def get_type(self):
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            text=data.get("text"),
            next_map=data.get("next"),
            set_variable=data.get("set_variable"),
            add_interest=data.get("add_interest"),
            branch=data.get("branch"),
            llm_followup=data.get("llm_followup"),
        )


class MoveAskOpen(Move):
    def __init__(self, text: str, next_map: Optional[Dict[str, str]] = None,
                 set_variable: Optional[str] = None, add_interest_from_answer: Optional[bool] = None,
                 add_interest_from_variable: Optional[str] = None, branch: Optional[str] = None,
                 personalize_followup: Optional[bool] = None, llm_followup: Optional[str] = None):
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
        # Optional LLM-generated followup: system prompt string, generated after the user replies
        self.llm_followup = llm_followup

    def get_type(self):
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            text=data.get("text"),
            next_map=data.get("next"),
            set_variable=data.get("set_variable"),
            add_interest_from_variable=data.get("add_interest_from_variable"),
            add_interest_from_answer=data.get("add_interest_from_answer"),
            branch=data.get("branch"),
            personalize_followup=data.get("personalize_followup"),
            llm_followup=data.get("llm_followup"),
        )


class MoveAskOptions(Move):
    def __init__(self, text: str, options: List[str], next_map: Optional[Dict[str, str]] = None,
                 set_variable: Optional[str] = None,
                 add_interest_from_variable: Optional[str] = None, branch: Optional[str] = None,
                 llm_followup: Optional[str] = None):
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
        # Optional LLM-generated followup: system prompt string, generated after the user replies
        self.llm_followup = llm_followup

    def get_type(self):
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            text=data.get("text"),
            options=data.get("options"),
            next_map=data.get("next"),
            set_variable=data.get("set_variable"),
            add_interest_from_variable=data.get("add_interest_from_variable"),
            branch=data.get("branch"),
            llm_followup=data.get("llm_followup"),
        )


class MoveAskLLM(Move):
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
    def __init__(self, audio_file: str):
        super().__init__()
        self.type = MOVE_PLAY_AUDIO
        self.audio_file = audio_file

    def get_type(self):
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            audio_file=data.get("audio"),
        )


class MoveMotionSequence(Move):
    def __init__(self, sequence_file: str):
        super().__init__()
        self.type = MOVE_MOTION_SEQUENCE
        self.sequence_file = sequence_file

    def get_type(self):
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            sequence_file=data.get("motion_sequence"),
        )


class MoveAnimation(Move):
    def __init__(self, animation_name: str):
        super().__init__()
        self.type = MOVE_ANIMATION
        self.animation_name = animation_name

    def get_type(self):
        return self.type

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            animation_name=data.get("animation_name"),
        )


