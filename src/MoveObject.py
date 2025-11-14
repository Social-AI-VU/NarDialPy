#  define Python classes for each move (Say, AskYesNo, AskOpen, AskOptions,
#  Play). Each object holds its data and knows how to execute itself (ask/say
#  , log to history, update user_model, handle branching, add interests).


class Move:
    branch: Optional[str] = None
    def execute(self, dialog, conversation_demo, session_history, user_model, topics_of_interest,
                idx: int, branch: Optional[str]) -> Tuple[int, Optional[str]]:
        raise NotImplementedError

class SayMove(Move):
    def __init__(self, text: str, branch: Optional[str] = None):
        self.text = text
        self.branch = branch
    def execute(self, dialog, conversation_demo, session_history, user_model, topics_of_interest,
                idx, branch):
        text = self.text
        for var, value in user_model.items():
            text = text.replace(f"%{var}%", str(value))
        conversation_demo.say(text)
        session_history.append({"role": "robot", "type": "say", "text": text})
        return idx + 1, branch

class AskYesNoMove(Move):
    def execute(self, dialog, conversation_demo, session_history, user_model, topics_of_interest,
                idx, branch):
        answer = conversation_demo.ask_yesno(self.text)
        session_history.append({"role": "robot", "type": "ask_yesno", "text": self.text})
        session_history.append({"role": "user", "type": "answer_yesno", "text": answer})
        norm = (answer or "").strip().lower()
        if self.set_variable:
            user_model[self.set_variable] = norm or None
        if norm == "yes" and self.add_interest:
            _add_interest(topics_of_interest, self.add_interest)
        # branching
        target = self.next_map.get(norm) or self.next_map.get("fail")
        if target:
            return dialog._find_branch_start(target), target
        return idx + 1, branch

def move_from_dict(d: Dict[str, Any]) -> Move:
    t = d.get("type")
    if t == "say":
        return SayMove(text=d["text"], branch=d.get("branch"))
    if t == "ask_yesno":
        return AskYesNoMove(
            text=d["text"],
            next_map=d.get("next"),
            set_variable=d.get("set_variable"),
            add_interest=d.get("add_interest"),
            branch=d.get("branch"),
        )
    # Fall back: keep as dict for types you haven’t converted yet
    # You can add AskOpenMove, AskOptionsMove, PlayMove similarly later.
    raise NotImplementedError(f"Move type not yet objectified: {t}")


    ```python
# filepath: c:\Users\georg\OneDrive\Documents\GitHub\NarDialPy\src\mini_dialogs.py
# ...existing code...
from moves import Move  # add this import at the top of the file
# ...existing code inside MiniDialog.run loop...
            move = self.moves[idx]
            # If this move is an object, let it execute itself
            if hasattr(move, "execute"):
                idx, branch = move.execute(self, conversation_demo, session_history, user_model, topics_of_interest, idx, branch)
                continue
            # existing dict-based handling below
            move_type = move.get('type')
            move_branch = move.get('branch')
# ...existing code...



```python
# filepath: c:\Users\georg\OneDrive\Documents\GitHub\NarDialPy\src\mini_dialogs.py
from moves import SayMove, AskYesNoMove
# ...existing code...
    ChitchatDialog(
        dialog_id="pineapple_on_pizza",
        theme="food",
        topics=["pizza", "pineapple", "food"],
        moves=[
            SayMove("Do you like pineapple on pizza?"),
            AskYesNoMove("Yes or no?", set_variable="likes_pineapple_pizza", add_interest="pizza"),
        ]
    ),
# ...existing code...