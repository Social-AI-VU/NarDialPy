import ast
import json
from os.path import abspath, dirname, join

from nardial.authoring.loader import load_dialogs


REPO_ROOT = abspath(join(dirname(__file__), ".."))
DIALOG_PATH = join(REPO_ROOT, "examples", "structured_conversation_dialogs.json")
DEMO_PATH = join(REPO_ROOT, "examples", "demo_structured_conversation.py")


def test_structured_dialog_json_loads_without_errors():
    dialogs, errors = load_dialogs(DIALOG_PATH)

    assert errors == []
    assert {d.dialog_id for d in dialogs} == {
        "welcome_and_name",
        "plan_activity",
        "adapt_to_user_energy",
        "structured_goodbye",
    }


def test_structured_dialog_json_includes_required_branching_patterns():
    with open(DIALOG_PATH, "r", encoding="utf-8") as f:
        docs = json.load(f)

    moves = [m for doc in docs for m in doc.get("moves", [])]

    # Branching based on current outcome
    assert any(m.get("type") == "branch" and m.get("on") == "outcome" for m in moves)
    # Branching based on persisted user model variable
    assert any(m.get("type") == "branch" and m.get("on") == "energy_level" for m in moves)

    # Variable extraction and persistence examples
    set_variables = {m.get("set_variable") for m in moves if m.get("set_variable")}
    assert {"first_name", "preferred_activity", "energy_level", "recharge_habit"}.issubset(set_variables)

    # Demo should include all move types used by MiniDialog runtime
    move_types = {m.get("type") for m in moves}
    assert {
        "say",
        "ask_open",
        "ask_options",
        "ask_yesno",
        "ask_llm",
        "play",
        "motion_sequence",
        "animation",
        "branch",
    }.issubset(move_types), "Demo must include all move types supported by MiniDialog runtime"

    # llm_followup is currently supported on ask_open / ask_yesno / ask_options (not ask_llm)
    assert any(
        m.get("llm_followup") for m in moves if m.get("type") in {"ask_open", "ask_yesno", "ask_options"}
    ), "Demo must demonstrate llm_followup on at least one ask_* move"


def test_structured_demo_declares_expected_agenda_order():
    with open(DEMO_PATH, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    session_agenda = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "session_agenda":
                    session_agenda = []
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            session_agenda.append(elt.value)
                        elif isinstance(elt, ast.Str):
                            session_agenda.append(elt.s)

    assert session_agenda == [
        "welcome_and_name",
        "plan_activity",
        "adapt_to_user_energy",
        "structured_goodbye",
    ]
