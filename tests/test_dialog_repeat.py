from types import SimpleNamespace

from nardial.dialog_repeat import dialog_has_repeat_prompt, user_confirmed_repeat
from nardial.moves import MOVE_ANSWER_YESNO


def test_dialog_has_repeat_prompt():
    d = SimpleNamespace(repeatable=True, repeat_moves=[{"type": "ask_yesno"}])
    assert dialog_has_repeat_prompt(d)
    assert not dialog_has_repeat_prompt(SimpleNamespace(repeatable=True, repeat_moves=[]))


def test_user_confirmed_repeat():
    tail = [{"role": "user", "type": MOVE_ANSWER_YESNO, "text": "yes"}]
    assert user_confirmed_repeat(tail)
    assert not user_confirmed_repeat([{"role": "user", "type": MOVE_ANSWER_YESNO, "text": "no"}])
