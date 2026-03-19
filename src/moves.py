from typing import Optional
from typing import Dict, Any, List
from abc import abstractmethod

MOVE_SAY = "say"
MOVE_ASK_YESNO = "ask_yesno"
MOVE_ASK_OPEN = "ask_open"
MOVE_ASK_OPTIONS = "ask_options"
MOVE_PLAY_AUDIO = "play"

MOVE_ANSWER_OPEN = "answer_open"


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
        return cls(
            text=data.get("text"),
            next_map=data.get("next"),
            set_variable=data.get("set_variable"),
            add_interest=data.get("add_interest"),
            branch=data.get("branch"),
        )


class MoveAskOpen(Move):
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
    def __init__(self, text: str, options: List[str], next_map: Optional[Dict[str, str]] = None, set_variable: Optional[str] = None,
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
        return cls(
            text=data.get("text"),
            options=data.get("options"),
            next_map=data.get("next"),
            set_variable=data.get("set_variable"),
            add_interest_from_variable=data.get("add_interest_from_variable"),
            branch=data.get("branch")
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
