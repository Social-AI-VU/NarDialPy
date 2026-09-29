import json

import pytest

from nardial import dialog_types, eligibility
from nardial.agenda.items import AgendaContext, ChitchatSlot
from nardial.authoring.factory import DialogFactory, DialogTypeFactory
from nardial.authoring.loader import load_dialog_registry, load_dialog_types, load_dialogs
from nardial.dialog_types import get_dialog_type
from nardial.eligibility import EligibilityRule, is_dialog_eligible, register_rule
from nardial.mini_dialogs import ChitchatDialog, DialogType, FunctionalDialog
from nardial.session_manager import SessionManager


class TimeOfDayIsRule(EligibilityRule):
    def __init__(self, value):
        self.value = value

    def is_eligible(self, dialog, context):
        return context.user_model.get("time_of_day") == self.value


class FromSessionRule(EligibilityRule):
    def __init__(self, min):
        self.min = min

    def is_eligible(self, dialog, context):
        return context.session_index is not None and context.session_index >= self.min


@pytest.fixture(autouse=True)
def isolated_registries(monkeypatch):
    # Types/rules registered in a test must not leak into other tests.
    monkeypatch.setattr(dialog_types, "_DIALOG_TYPES", dict(dialog_types._DIALOG_TYPES))
    monkeypatch.setattr(eligibility, "_RULES", dict(eligibility._RULES))
    # Custom rules, registered the way package users would.
    register_rule("time_of_day_is")(TimeOfDayIsRule)
    register_rule("from_session")(FromSessionRule)


EVENING_TYPE = {
    "define_type": "evening_chitchat",
    "extends": "chitchat",
    "description": "Chitchat that only runs in the evening, and may repeat.",
    "remove_rules": ["exclude_if_seen"],
    "add_rules": [{"rule": "time_of_day_is", "value": "evening"}],
}
EVENING_DIALOG = {
    "id": "evening_music",
    "type": "evening_chitchat",
    "topics": ["music"],
    "moves": [{"type": "say", "text": "Good evening"}],
}
EVENING = {"time_of_day": "evening"}
MORNING = {"time_of_day": "morning"}


def rule_names_of(cls):
    return [rule.RULE_NAME for rule in cls.DEFAULT_ELIGIBILITY]


def test_contexts_default_to_unknown_session():
    assert AgendaContext().session_index is None
    assert eligibility.EligibilityContext().session_index is None


# --- DialogTypeFactory ---

def test_define_type_builds_registered_subclass():
    cls = DialogTypeFactory.from_json(EVENING_TYPE)

    assert get_dialog_type("evening_chitchat") is cls
    assert issubclass(cls, ChitchatDialog)
    assert cls.__name__ == "EveningChitchat"
    assert cls.__doc__ == EVENING_TYPE["description"]
    assert cls.TYPE_NAME == "evening_chitchat"
    assert cls.DIALOG_TYPE == DialogType.CHITCHAT
    assert rule_names_of(cls) == ["dependency_met", "variable_dependency_met", "time_of_day_is"]
    # The parent's rules are untouched.
    assert rule_names_of(ChitchatDialog) == ["exclude_if_seen", "dependency_met", "variable_dependency_met"]


def test_defined_type_dialog_uses_its_rules():
    DialogTypeFactory.from_json(EVENING_TYPE)
    dialog = DialogFactory.from_json(EVENING_DIALOG)

    assert not is_dialog_eligible(dialog, AgendaContext(user_model=MORNING))
    assert is_dialog_eligible(dialog, AgendaContext(user_model=EVENING))
    # exclude_if_seen was removed, so it stays eligible after being completed.
    assert is_dialog_eligible(dialog, AgendaContext(user_model=EVENING, completed_ids=["evening_music"]))


def test_defined_type_can_extend_a_defined_type():
    DialogTypeFactory.from_json(EVENING_TYPE)
    cls = DialogTypeFactory.from_json({
        "define_type": "late_evening_chitchat",
        "extends": "evening_chitchat",
        "add_rules": [{"rule": "from_session", "min": 2}],
    })

    assert issubclass(cls, get_dialog_type("evening_chitchat"))
    assert rule_names_of(cls) == ["dependency_met", "variable_dependency_met", "time_of_day_is", "from_session"]


def test_define_type_with_no_rule_changes_copies_parent_rules():
    cls = DialogTypeFactory.from_json({"define_type": "greeting_variant", "extends": "functional"})
    assert rule_names_of(cls) == rule_names_of(FunctionalDialog)
    assert cls.DEFAULT_ELIGIBILITY is not FunctionalDialog.DEFAULT_ELIGIBILITY


def test_redefining_identical_type_returns_existing_class():
    first = DialogTypeFactory.from_json(EVENING_TYPE)
    assert DialogTypeFactory.from_json(json.loads(json.dumps(EVENING_TYPE))) is first


def test_redefining_type_differently_raises():
    DialogTypeFactory.from_json(EVENING_TYPE)
    with pytest.raises(ValueError, match="already registered"):
        DialogTypeFactory.from_json({**EVENING_TYPE, "add_rules": []})


def test_define_type_cannot_override_builtin():
    with pytest.raises(ValueError, match="already registered"):
        DialogTypeFactory.from_json({"define_type": "chitchat", "extends": "chitchat"})


@pytest.mark.parametrize("doc, message", [
    ({"define_type": "", "extends": "chitchat"}, "define_type must be non-empty string"),
    ({"define_type": "x", "extends": "nope"}, "extends must be one of 'functional'"),
    ({"define_type": "x"}, "extends must be one of"),
    ({"define_type": "x", "extends": "chitchat", "rules": []}, "unknown key 'rules' in type definition"),
    ({"define_type": "x", "extends": "chitchat", "description": 1}, "description must be string"),
    ({"define_type": "x", "extends": "chitchat", "add_rules": {}}, "add_rules must be a list"),
    ({"define_type": "x", "extends": "chitchat", "add_rules": ["nope"]}, "add_rules[0]: unknown eligibility rule 'nope'"),
    ({"define_type": "x", "extends": "chitchat", "remove_rules": "exclude_if_seen"}, "remove_rules must be a list of rule names"),
    ({"define_type": "x", "extends": "functional", "remove_rules": ["exclude_if_seen"]},
     "remove_rules[0]: 'exclude_if_seen' is not a rule of 'functional' (its rules: dependency_met)"),
])
def test_define_type_validation(doc, message):
    errors = DialogTypeFactory.validate_doc(doc)
    assert any(message in e for e in errors), errors
    with pytest.raises(ValueError):
        DialogTypeFactory.from_json(doc)
    assert get_dialog_type("x") is None


# --- loader ---

def _write(path, docs):
    path.write_text(json.dumps(docs), encoding="utf-8")


def test_load_dialog_types_then_dialogs(tmp_path):
    _write(tmp_path / "types.json", [EVENING_TYPE])
    _write(tmp_path / "dialogs.json", [EVENING_DIALOG])

    types, errors = load_dialog_types(str(tmp_path / "types.json"))
    assert errors == []
    assert types == [get_dialog_type("evening_chitchat")]

    dialogs, errors = load_dialogs(str(tmp_path / "dialogs.json"))
    assert errors == []
    assert [type(d) for d in dialogs] == types


def test_dialogs_need_their_types_loaded_first(tmp_path):
    _write(tmp_path / "dialogs.json", [EVENING_DIALOG])

    dialogs, errors = load_dialogs(str(tmp_path / "dialogs.json"))

    assert dialogs == []
    assert len(errors) == 1
    assert "type must be" in errors[0]


def test_type_definition_in_dialog_file_is_rejected(tmp_path):
    good = {"id": "plain_chat", "type": "chitchat", "moves": []}
    _write(tmp_path / "dialogs.json", [EVENING_TYPE, good])

    dialogs, errors = load_dialogs(str(tmp_path / "dialogs.json"))

    assert [d.dialog_id for d in dialogs] == ["plain_chat"]
    assert len(errors) == 1
    assert "dialog type definition 'evening_chitchat' found in a dialog file" in errors[0]
    assert "load_dialog_types()" in errors[0]
    # It was not registered as a side effect either.
    assert get_dialog_type("evening_chitchat") is None


def test_dialog_in_types_file_is_rejected(tmp_path):
    _write(tmp_path / "types.json", [EVENING_TYPE, EVENING_DIALOG])

    types, errors = load_dialog_types(str(tmp_path / "types.json"))

    assert types == [get_dialog_type("evening_chitchat")]
    assert len(errors) == 1
    assert "not a dialog type definition (missing 'define_type')" in errors[0]


def test_load_dialog_types_resolves_chain_across_files_in_any_order(tmp_path):
    types_dir = tmp_path / "types"
    types_dir.mkdir()
    _write(types_dir / "a_child.json", {
        "define_type": "late_evening_chitchat",
        "extends": "evening_chitchat",
        "add_rules": [{"rule": "from_session", "min": 2}],
    })
    _write(types_dir / "b_parent.json", EVENING_TYPE)
    _write(tmp_path / "dialogs.json", [{**EVENING_DIALOG, "type": "late_evening_chitchat"}])

    types, errors = load_dialog_types(str(types_dir))
    assert errors == []
    assert {t.TYPE_NAME for t in types} == {"evening_chitchat", "late_evening_chitchat"}

    registry, errors = load_dialog_registry(str(tmp_path / "dialogs.json"))
    assert errors == []
    dialog = registry.get_by_id("evening_music")
    assert dialog.TYPE_NAME == "late_evening_chitchat"
    # Still selected by chitchat slots.
    assert registry.get_by_type(DialogType.CHITCHAT) == [dialog]


def test_load_dialog_types_reports_bad_definition_without_dropping_others(tmp_path):
    other = {"define_type": "other_chitchat", "extends": "chitchat"}
    _write(tmp_path / "types.json", [{**EVENING_TYPE, "add_rules": ["nope"]}, other])

    types, errors = load_dialog_types(str(tmp_path / "types.json"))

    assert types == [get_dialog_type("other_chitchat")]
    assert len(errors) == 1
    assert "unknown eligibility rule 'nope'" in errors[0]


def test_load_dialog_types_reports_definition_cycle(tmp_path):
    _write(tmp_path / "types.json", [
        {"define_type": "a_type", "extends": "b_type"},
        {"define_type": "b_type", "extends": "a_type"},
    ])

    types, errors = load_dialog_types(str(tmp_path / "types.json"))

    assert types == []
    assert len(errors) == 2
    assert all("extends must be one of" in e for e in errors)


def test_loading_same_types_twice_is_fine(tmp_path):
    _write(tmp_path / "types.json", [EVENING_TYPE])

    first, errors = load_dialog_types(str(tmp_path / "types.json"))
    assert errors == []
    second, errors = load_dialog_types(str(tmp_path / "types.json"))
    assert errors == []
    assert second == first


def test_defined_type_dialog_resolves_in_chitchat_slot(tmp_path):
    _write(tmp_path / "types.json", [EVENING_TYPE])
    _write(tmp_path / "dialogs.json", [EVENING_DIALOG])
    load_dialog_types(str(tmp_path / "types.json"))
    registry, _ = load_dialog_registry(str(tmp_path / "dialogs.json"))

    slot = ChitchatSlot()
    assert slot.resolve(AgendaContext(registry=registry, user_model=MORNING)) is None
    assert slot.resolve(AgendaContext(registry=registry, user_model=EVENING)) is registry.get_by_id("evening_music")


# --- SessionManager ---

@pytest.mark.parametrize("session_index, expected", [
    (1, ["Hello!"]),
    (2, ["Hello!", "Welcome back"]),
])
def test_session_manager_loads_types_and_passes_session_index(tmp_path, monkeypatch, make_mock_agent,
                                                              session_index, expected):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "types.json", [{
        "define_type": "returning_chitchat",
        "extends": "chitchat",
        "add_rules": [{"rule": "from_session", "min": 2}],
    }])
    _write(tmp_path / "dialogs.json", [
        {"id": "greeting_1", "type": "functional", "functional_type": "greeting",
         "moves": [{"type": "say", "text": "Hello!"}]},
        {"id": "welcome_back", "type": "returning_chitchat", "moves": [{"type": "say", "text": "Welcome back"}]},
    ])
    agent = make_mock_agent()

    manager = SessionManager(
        session_agenda=["greeting_1", "welcome_back"],
        agent=agent,
        dialog_types_path=str(tmp_path / "types.json"),
        dialog_json_path=str(tmp_path / "dialogs.json"),
        participant_id=f"p_session_rule_{session_index}",
        session_index=session_index,
    )
    assert manager.dialog_types_path == str(tmp_path / "types.json")
    assert manager.registry.get_by_id("welcome_back") is not None
    assert manager._build_agenda_context().session_index == session_index
    manager.run()

    assert [call.args[0] for call in agent.say.call_args_list] == expected
