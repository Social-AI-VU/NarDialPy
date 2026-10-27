import pytest

from nardial import dialog_types
from nardial.agenda.items import AgendaContext, ChitchatSlot
from nardial.authoring.factory import DialogFactory
from nardial.dialog_registry import DialogRegistry
from nardial.dialog_types import dialog_type_names, get_dialog_type, register_dialog_type
from nardial.eligibility import EligibilityRule, is_dialog_eligible
from nardial.mini_dialogs import (
    ChitchatDialog,
    DialogType,
    FunctionalDialog,
    LLMDialog,
    MiniDialog,
    NarrativeDialog,
)


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    # Custom types registered in a test must not leak into other tests.
    monkeypatch.setattr(dialog_types, "_DIALOG_TYPES", dict(dialog_types._DIALOG_TYPES))


class RequiresEveningRule(EligibilityRule):
    def is_eligible(self, dialog, context):
        return context.user_model.get("time_of_day") == "evening"


def _register_evening_chitchat():
    @register_dialog_type("evening_chitchat")
    class EveningChitchat(ChitchatDialog):
        DEFAULT_ELIGIBILITY = ChitchatDialog.DEFAULT_ELIGIBILITY + [RequiresEveningRule()]

    return EveningChitchat


def _evening_doc(**overrides):
    doc = {
        "id": "evening_music",
        "type": "evening_chitchat",
        "topics": ["music"],
        "moves": [{"type": "say", "text": "Good evening"}],
    }
    doc.update(overrides)
    return doc


def test_builtin_types_are_registered():
    assert get_dialog_type("functional") is FunctionalDialog
    assert get_dialog_type("narrative") is NarrativeDialog
    assert get_dialog_type("chitchat") is ChitchatDialog
    assert get_dialog_type("llm_based") is LLMDialog
    assert dialog_type_names()[:4] == ["functional", "narrative", "chitchat", "llm_based"]


def test_unknown_type_error_lists_registered_types():
    _register_evening_chitchat()
    errors = DialogFactory.validate_doc(_evening_doc(type="nope"))
    assert "type must be 'functional' | 'narrative' | 'chitchat' | 'llm_based' | 'evening_chitchat'" in errors


def test_custom_type_loads_from_json_with_inherited_fields():
    cls = _register_evening_chitchat()
    dialog = DialogFactory.from_json(_evening_doc())

    assert type(dialog) is cls
    assert dialog.topics == ["music"]
    assert dialog.TYPE_NAME == "evening_chitchat"
    assert dialog.DIALOG_TYPE == DialogType.CHITCHAT


def test_custom_type_inherits_parent_validation():
    _register_evening_chitchat()
    errors = DialogFactory.validate_doc(_evening_doc(topics="music"))
    assert "topics must be a list of strings for chitchat dialogs" in errors


def test_custom_type_roundtrips_its_type_name():
    _register_evening_chitchat()
    serialized = DialogFactory.to_json(DialogFactory.from_json(_evening_doc()))

    assert serialized["type"] == "evening_chitchat"
    assert serialized["topics"] == ["music"]
    assert DialogFactory.from_json(serialized).TYPE_NAME == "evening_chitchat"


def test_custom_type_uses_its_own_eligibility_rules():
    _register_evening_chitchat()
    dialog = DialogFactory.from_json(_evening_doc())

    assert not is_dialog_eligible(dialog, AgendaContext(user_model={"time_of_day": "morning"}))
    assert is_dialog_eligible(dialog, AgendaContext(user_model={"time_of_day": "evening"}))
    # Inherited ExcludeIfSeenRule still applies.
    assert not is_dialog_eligible(
        dialog, AgendaContext(user_model={"time_of_day": "evening"}, completed_ids=["evening_music"])
    )


def test_chitchat_slot_picks_up_custom_subtype():
    _register_evening_chitchat()
    dialog = DialogFactory.from_json(_evening_doc())
    registry = DialogRegistry.build([dialog])

    slot = ChitchatSlot()
    assert slot.resolve(AgendaContext(registry=registry, user_model={"time_of_day": "evening"})) is dialog
    assert slot.resolve(AgendaContext(registry=registry, user_model={"time_of_day": "morning"})) is None


def test_custom_type_can_add_its_own_fields():
    @register_dialog_type("quiz")
    class QuizDialog(MiniDialog):
        def __init__(self, dialog_id, moves, difficulty, **kwargs):
            super().__init__(dialog_id, moves, **kwargs)
            self.difficulty = difficulty

        @classmethod
        def validate_doc(cls, doc):
            errs = super().validate_doc(doc)
            if not isinstance(doc.get("difficulty"), int):
                errs.append("difficulty must be integer for quiz dialogs")
            return errs

        @classmethod
        def from_doc(cls, doc, **common):
            return cls(difficulty=doc["difficulty"], **common)

        def to_doc(self):
            return {**super().to_doc(), "difficulty": self.difficulty}

    doc = {"id": "q1", "type": "quiz", "difficulty": 3, "moves": []}
    assert DialogFactory.validate_doc({**doc, "difficulty": "hard"}) == ["difficulty must be integer for quiz dialogs"]

    dialog = DialogFactory.from_json(doc)
    assert isinstance(dialog, QuizDialog)
    assert DialogFactory.to_json(dialog)["difficulty"] == 3


def test_registering_taken_name_to_other_class_raises():
    with pytest.raises(ValueError, match="already registered"):
        @register_dialog_type("chitchat")
        class Impostor(ChitchatDialog):
            pass

    assert get_dialog_type("chitchat") is ChitchatDialog


def test_reregistering_same_class_is_noop():
    register_dialog_type("chitchat")(ChitchatDialog)
    assert get_dialog_type("chitchat") is ChitchatDialog
