"""Tests for the authoring layer: Pydantic schemas, factory round-trips, and file I/O."""
import json
import pytest
from pydantic import ValidationError, TypeAdapter

from nardial.moves import (
    MoveSay, MoveAskYesNo, MoveAskOpen, MoveAskOptions, MoveAskLLM,
    MovePlayAudio, MoveMotionSequence, MoveAnimation, MoveBranch, AnyMove,
)
from nardial.authoring.schemas import (
    FunctionalDialogSpec, NarrativeDialogSpec, ChitchatDialogSpec, LLMDialogSpec,
)
from nardial.authoring.factory import from_json, to_json
from nardial.authoring.loader import load_dialogs, save_dialogs, save_dialogs_to_dir
from nardial.mini_dialogs import FunctionalDialog, NarrativeDialog, ChitchatDialog, LLMDialog


# ── Canonical dialog documents used across multiple tests ─────────────────────

FUNCTIONAL_DOC = {
    "id": "greeting",
    "type": "functional",
    "functional_type": "greeting",
    "moves": [{"type": "say", "text": "Hello!"}],
}
NARRATIVE_DOC = {
    "id": "chapter_1",
    "type": "narrative",
    "thread": "main",
    "position": 1,
    "moves": [{"type": "say", "text": "Once upon a time..."}],
}
CHITCHAT_DOC = {
    "id": "cats_chat",
    "type": "chitchat",
    "topics": ["cats", "dogs"],
}
LLM_DOC = {
    "id": "open_chat",
    "type": "llm_based",
    "prompt": "Chat warmly with the user.",
    "max_turns": 4,
}


# ── Move model parsing ────────────────────────────────────────────────────────

class TestMoveParsing:
    """Each move type must parse from a plain dict via model_validate."""

    def test_move_say(self):
        m = MoveSay.model_validate({"type": "say", "text": "Hello"})
        assert m.text == "Hello"

    def test_move_ask_yesno_with_set_variable(self):
        m = MoveAskYesNo.model_validate({"type": "ask_yesno", "text": "Do you?", "set_variable": "ans"})
        assert m.set_variable == "ans"

    def test_move_ask_open_defaults(self):
        m = MoveAskOpen.model_validate({"type": "ask_open", "text": "Tell me more."})
        assert m.add_interest_from_answer is None
        assert m.llm_followup is None

    def test_move_ask_options(self):
        m = MoveAskOptions.model_validate({"type": "ask_options", "text": "Choose", "options": ["a", "b"]})
        assert m.options == ["a", "b"]

    def test_move_ask_options_empty_list_rejected(self):
        with pytest.raises(ValidationError):
            MoveAskOptions.model_validate({"type": "ask_options", "text": "Choose", "options": []})

    def test_move_ask_llm(self):
        m = MoveAskLLM.model_validate({"type": "ask_llm", "prompt": "Chat", "max_turns": 3})
        assert m.max_turns == 3

    def test_move_play_audio(self):
        m = MovePlayAudio.model_validate({"type": "play", "audio": "sound.wav"})
        assert m.audio == "sound.wav"

    def test_move_motion_sequence(self):
        m = MoveMotionSequence.model_validate({"type": "motion_sequence", "motion_sequence": "wave"})
        assert m.motion_sequence == "wave"

    def test_move_animation(self):
        m = MoveAnimation.model_validate({"type": "animation", "animation_name": "Stand/Wave"})
        assert m.animation_name == "Stand/Wave"

    def test_move_branch_with_nested_moves(self):
        m = MoveBranch.model_validate({
            "type": "branch",
            "on": "outcome",
            "cases": {
                "yes": [{"type": "say", "text": "Great!"}],
                "no": [{"type": "say", "text": "Too bad."}],
            },
        })
        assert len(m.cases["yes"]) == 1
        assert m.cases["no"][0].text == "Too bad."

    def test_move_branch_nested_recursively(self):
        """MoveBranch.cases can contain another MoveBranch (recursive AnyMove type)."""
        m = MoveBranch.model_validate({
            "type": "branch",
            "on": "outcome",
            "cases": {
                "a": [{"type": "branch", "on": "mood", "cases": {
                    "happy": [{"type": "say", "text": "Yay!"}]
                }}],
            },
        })
        inner = m.cases["a"][0]
        assert isinstance(inner, MoveBranch)
        assert inner.cases["happy"][0].text == "Yay!"

    def test_unknown_move_type_rejected_by_discriminated_union(self):
        adapter = TypeAdapter(AnyMove)
        with pytest.raises((ValidationError, Exception)):
            adapter.validate_python({"type": "does_not_exist", "text": "hi"})


# ── Dialog spec parsing ───────────────────────────────────────────────────────

class TestDialogSpecParsing:
    def test_functional_spec_greeting(self):
        spec = FunctionalDialogSpec.model_validate(FUNCTIONAL_DOC)
        assert spec.functional_type == "greeting"
        assert len(spec.moves) == 1

    def test_functional_spec_farewell(self):
        spec = FunctionalDialogSpec.model_validate({
            "id": "bye", "type": "functional", "functional_type": "farewell"
        })
        assert spec.functional_type == "farewell"

    def test_functional_spec_invalid_functional_type_rejected(self):
        with pytest.raises(ValidationError):
            FunctionalDialogSpec.model_validate({
                "id": "x", "type": "functional", "functional_type": "unknown_type",
            })

    def test_narrative_spec(self):
        spec = NarrativeDialogSpec.model_validate(NARRATIVE_DOC)
        assert spec.thread == "main"
        assert spec.position == 1

    def test_chitchat_spec_with_topics(self):
        spec = ChitchatDialogSpec.model_validate(CHITCHAT_DOC)
        assert spec.topics == ["cats", "dogs"]

    def test_chitchat_spec_topics_default_empty(self):
        spec = ChitchatDialogSpec.model_validate({"id": "c1", "type": "chitchat"})
        assert spec.topics == []

    def test_llm_spec_defaults(self):
        spec = LLMDialogSpec.model_validate(LLM_DOC)
        assert spec.max_turns == 4
        assert spec.speak_first is True
        assert spec.rag_enabled is False

    def test_variable_dependency_string_coerced_to_dict(self):
        """A bare string is normalised to {"variable": str, "required": True}."""
        spec = NarrativeDialogSpec.model_validate({
            "id": "n1", "type": "narrative", "thread": "t", "position": 1,
            "variable_dependencies": ["name"],
        })
        vd = spec.variable_dependencies[0]
        assert vd.variable == "name"
        assert vd.required is True

    def test_variable_dependency_dict_form_optional(self):
        spec = NarrativeDialogSpec.model_validate({
            "id": "n1", "type": "narrative", "thread": "t", "position": 1,
            "variable_dependencies": [{"variable": "age", "required": False}],
        })
        assert spec.variable_dependencies[0].required is False


# ── from_json / to_json round-trips ──────────────────────────────────────────

@pytest.mark.parametrize("doc,expected_cls", [
    (FUNCTIONAL_DOC, FunctionalDialog),
    (NARRATIVE_DOC, NarrativeDialog),
    (CHITCHAT_DOC, ChitchatDialog),
    (LLM_DOC, LLMDialog),
])
def test_from_json_returns_correct_runtime_type(doc, expected_cls):
    dialog = from_json(doc)
    assert isinstance(dialog, expected_cls)


@pytest.mark.parametrize("doc", [FUNCTIONAL_DOC, NARRATIVE_DOC, CHITCHAT_DOC, LLM_DOC])
def test_round_trip_preserves_dialog_id(doc):
    dialog = from_json(doc)
    serialized = to_json(dialog)
    reloaded = from_json(serialized)
    assert reloaded.dialog_id == dialog.dialog_id


def test_round_trip_preserves_moves():
    dialog = from_json(NARRATIVE_DOC)
    serialized = to_json(dialog)
    assert serialized["moves"][0]["text"] == "Once upon a time..."


def test_round_trip_preserves_narrative_position():
    dialog = from_json(NARRATIVE_DOC)
    serialized = to_json(dialog)
    assert serialized["position"] == 1
    assert serialized["thread"] == "main"


def test_round_trip_preserves_chitchat_topics():
    dialog = from_json(CHITCHAT_DOC)
    serialized = to_json(dialog)
    assert serialized["topics"] == ["cats", "dogs"]


def test_round_trip_preserves_llm_max_turns():
    dialog = from_json(LLM_DOC)
    serialized = to_json(dialog)
    assert serialized["max_turns"] == 4


def test_from_json_invalid_type_raises():
    with pytest.raises(Exception):
        from_json({"id": "x", "type": "not_a_real_type"})


def test_from_json_with_branch_move():
    doc = {
        "id": "branch_dialog",
        "type": "narrative",
        "thread": "t",
        "position": 1,
        "moves": [
            {"type": "ask_yesno", "text": "Do you like cats?",
             "outcomes": {"yes": "cat_fan", "no": "no_cat"}},
            {"type": "branch", "on": "outcome", "cases": {
                "cat_fan": [{"type": "say", "text": "Me too!"}],
                "no_cat": [{"type": "say", "text": "That's fine."}],
            }},
        ],
    }
    dialog = from_json(doc)
    assert len(dialog.moves) == 2


# ── load_dialogs and save_dialogs ─────────────────────────────────────────────

class TestLoadDialogs:
    def test_load_single_json_file(self, tmp_path):
        path = tmp_path / "dialogs.json"
        path.write_text(json.dumps([FUNCTIONAL_DOC, NARRATIVE_DOC]))
        dialogs, errors = load_dialogs(str(path))
        assert len(dialogs) == 2
        assert errors == []

    def test_load_from_directory_reads_all_json_files(self, tmp_path):
        (tmp_path / "d1.json").write_text(json.dumps([FUNCTIONAL_DOC]))
        (tmp_path / "d2.json").write_text(json.dumps([NARRATIVE_DOC]))
        (tmp_path / "readme.txt").write_text("ignore me")
        dialogs, errors = load_dialogs(str(tmp_path))
        assert len(dialogs) == 2
        assert errors == []

    def test_invalid_entries_reported_as_errors(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps([{"id": "x", "type": "invalid_type_xyz"}]))
        dialogs, errors = load_dialogs(str(bad))
        assert dialogs == []
        assert len(errors) == 1

    def test_nonexistent_path_returns_error(self, tmp_path):
        _, errors = load_dialogs(str(tmp_path / "nonexistent.json"))
        assert len(errors) > 0

    def test_save_and_reload_preserves_dialog(self, tmp_path):
        out_file = str(tmp_path / "out.json")
        dialog = from_json(FUNCTIONAL_DOC)
        save_dialogs(out_file, [dialog])
        reloaded, errors = load_dialogs(out_file)
        assert errors == []
        assert len(reloaded) == 1
        assert reloaded[0].dialog_id == "greeting"

    def test_save_to_directory_creates_individual_files(self, tmp_path):
        dialogs = [from_json(FUNCTIONAL_DOC), from_json(NARRATIVE_DOC)]
        save_dialogs_to_dir(str(tmp_path), dialogs)
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 2

    def test_single_dict_root_also_accepted(self, tmp_path):
        """A JSON file with a dict root (not list) wraps it into a single-item list."""
        path = tmp_path / "single.json"
        path.write_text(json.dumps(FUNCTIONAL_DOC))
        dialogs, errors = load_dialogs(str(path))
        assert errors == []
        assert len(dialogs) == 1
