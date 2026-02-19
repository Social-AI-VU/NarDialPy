from typing import Optional
from typing import Dict, Any, List


class MoveSay:
    def __init__(self, text: str, branch: Optional[str] = None):
        # Basic move for saying a line. Matches schema: {"type":"say","text":..., "branch"?: str|null}
        self.type = "say"
        self.text = text
        self.branch = branch

    def as_dict(self) -> Dict[str, Any]:
        d = {"type": "say", "text": self.text}
        if self.branch is not None:
            d["branch"] = self.branch
        return d

    def __repr__(self) -> str:
        return f"MoveSay(text={self.text!r}, branch={self.branch!r})"

    def __str__(self) -> str:
        return self.text

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MoveSay):
            return False
        return self.text == other.text and self.branch == other.branch

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)


class MoveAskYesNo:
    def __init__(self, text: str, next_map: Optional[Dict[str, str]] = None,
                 set_variable: Optional[str] = None, add_interest: Optional[str] = None,
                 branch: Optional[str] = None):
        # Ensure compatibility with MiniDialog.run accessor expectations
        self.type = "ask_yesno"
        self.text = text
        # Engine reads 'next'; we also keep 'next_map' as an alias for convenience
        self.next = dict(next_map or {})
        self.next_map = self.next
        self.set_variable = set_variable
        self.add_interest = add_interest
        self.branch = branch

    def as_dict(self) -> Dict[str, Any]:
        d = {"type": "ask_yesno", "text": self.text}
        if self.next:
            d["next"] = self.next
        if self.set_variable is not None:
            d["set_variable"] = self.set_variable
        if self.add_interest is not None:
            d["add_interest"] = self.add_interest
        if self.branch is not None:
            d["branch"] = self.branch
        return d

    def __repr__(self) -> str:
        return f"MoveAskYesNo(text={self.text!r}, next={self.next!r}, set_variable={self.set_variable!r}, add_interest={self.add_interest!r}, branch={self.branch!r})"

    def __str__(self) -> str:
        return self.text

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MoveAskYesNo):
            return False
        return (self.text == other.text and
                self.next == other.next and
                self.set_variable == other.set_variable and
                self.add_interest == other.add_interest and
                self.branch == other.branch)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)


class MoveAskOpen:
    def __init__(self, text: str, next_map: Optional[Dict[str, str]] = None,
                 set_variable: Optional[str] = None,
                 add_interest_from_answer: Optional[bool] = None,
                 add_interest_from_variable: Optional[str] = None,
                 branch: Optional[str] = None):
        # Ensure compatibility with MiniDialog.run accessor expectations
        self.type = "ask_open"
        self.text = text
        # Engine reads 'next'; keep 'next_map' as alias for convenience
        self.next = dict(next_map or {})
        self.next_map = self.next
        self.set_variable = set_variable
        self.add_interest_from_answer = add_interest_from_answer
        self.add_interest_from_variable = add_interest_from_variable
        self.branch = branch

    def as_dict(self) -> Dict[str, Any]:
        d = {"type": "ask_open", "text": self.text}
        if self.next:
            d["next"] = self.next
        if self.set_variable is not None:
            d["set_variable"] = self.set_variable
        if self.add_interest_from_answer is not None:
            d["add_interest_from_answer"] = self.add_interest_from_answer
        if self.add_interest_from_variable is not None:
            d["add_interest_from_variable"] = self.add_interest_from_variable
        if self.branch is not None:
            d["branch"] = self.branch
        return d

    def __repr__(self) -> str:
        return f"MoveAskOpen(text={self.text!r}, next={self.next!r}, set_variable={self.set_variable!r}, add_interest_from_answer={self.add_interest_from_answer!r}, add_interest_from_variable={self.add_interest_from_variable!r}, branch={self.branch!r})"

    def __str__(self) -> str:
        return self.text

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MoveAskOpen):
            return False
        return (self.text == other.text and
                self.next == other.next and
                self.set_variable == other.set_variable and
                self.add_interest_from_answer == other.add_interest_from_answer and
                self.add_interest_from_variable == other.add_interest_from_variable and
                self.branch == other.branch)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)


class MoveAskOptions:
    def __init__(self, text: str, options: List[str],
                 next_map: Optional[Dict[str, str]] = None,
                 set_variable: Optional[str] = None,
                 add_interest_from_variable: Optional[str] = None,
                 branch: Optional[str] = None):
        # Ensure compatibility with MiniDialog.run accessor expectations
        self.type = "ask_options"
        self.text = text
        self.options = options
        # Engine reads 'next'; keep 'next_map' as alias for convenience
        self.next = dict(next_map or {})
        self.next_map = self.next
        self.set_variable = set_variable
        self.add_interest_from_variable = add_interest_from_variable
        self.branch = branch

    def as_dict(self) -> Dict[str, Any]:
        d = {"type": "ask_options", "text": self.text, "options": self.options}
        if self.next:
            d["next"] = self.next
        if self.set_variable is not None:
            d["set_variable"] = self.set_variable
        if self.add_interest_from_variable is not None:
            d["add_interest_from_variable"] = self.add_interest_from_variable
        if self.branch is not None:
            d["branch"] = self.branch
        return d

    def __repr__(self) -> str:
        return f"MoveAskOptions(text={self.text!r}, options={self.options!r}, next={self.next!r}, set_variable={self.set_variable!r}, add_interest_from_variable={self.add_interest_from_variable!r}, branch={self.branch!r})"

    def __str__(self) -> str:
        return self.text

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MoveAskOptions):
            return False
        return (self.text == other.text and
                self.options == other.options and
                self.next == other.next and
                self.set_variable == other.set_variable and
                self.add_interest_from_variable == other.add_interest_from_variable and
                self.branch == other.branch)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)
