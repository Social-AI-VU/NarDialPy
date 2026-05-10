"""Tests for DialogRegistry and load_dialog_registry."""

import json
import os
import pytest

from nardial.dialog_registry import DialogRegistry
from nardial.mini_dialogs import (
    ChitchatDialog,
    DialogType,
    FunctionalDialog,
    LLMDialog,
    NarrativeDialog,
)
from nardial.moves import MoveSay
from nardial.authoring.loader import load_dialog_registry


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_narrative(dialog_id, thread="main", position=1):
    return NarrativeDialog(dialog_id=dialog_id, moves=[], thread=thread, position=position)


def make_chitchat(dialog_id, topics=None):
    return ChitchatDialog(dialog_id=dialog_id, moves=[], topics=topics or [])


def make_functional(dialog_id, functional_type="greeting"):
    return FunctionalDialog(dialog_id=dialog_id, moves=[], functional_type=functional_type)


def make_llm(dialog_id):
    return LLMDialog(dialog_id=dialog_id, prompt="Chat with the user.")


# ── DialogRegistry.build ──────────────────────────────────────────────────────

class TestDialogRegistryBuild:
    def test_by_id_populated(self):
        n = make_narrative("n1")
        reg = DialogRegistry.build([n])
        assert reg.get_by_id("n1") is n

    def test_get_by_id_returns_none_for_missing(self):
        reg = DialogRegistry.build([])
        assert reg.get_by_id("nonexistent") is None

    def test_by_type_narrative(self):
        n = make_narrative("n1")
        c = make_chitchat("c1")
        reg = DialogRegistry.build([n, c])
        assert reg.get_by_type(DialogType.NARRATIVE) == [n]

    def test_by_type_chitchat(self):
        c = make_chitchat("c1")
        reg = DialogRegistry.build([c])
        assert reg.get_by_type(DialogType.CHITCHAT) == [c]

    def test_by_type_functional(self):
        f = make_functional("greeting")
        reg = DialogRegistry.build([f])
        assert reg.get_by_type(DialogType.FUNCTIONAL) == [f]

    def test_by_type_llm(self):
        d = make_llm("llm1")
        reg = DialogRegistry.build([d])
        assert reg.get_by_type(DialogType.LLM_BASED) == [d]

    def test_by_type_empty_list_for_absent_type(self):
        reg = DialogRegistry.build([make_narrative("n1")])
        assert reg.get_by_type(DialogType.CHITCHAT) == []

    def test_duplicate_id_skips_second(self, caplog):
        n1 = make_narrative("dup")
        n2 = make_narrative("dup")
        import logging
        with caplog.at_level(logging.WARNING):
            reg = DialogRegistry.build([n1, n2])
        assert reg.get_by_id("dup") is n1
        assert len(reg) == 1
        assert "dup" in caplog.text

    def test_len_reflects_unique_dialogs(self):
        reg = DialogRegistry.build([make_narrative("n1"), make_chitchat("c1")])
        assert len(reg) == 2

    def test_repr(self):
        reg = DialogRegistry.build([make_narrative("n1")])
        assert "1" in repr(reg)


# ── get_by_attr — scalar (thread) ─────────────────────────────────────────────

class TestGetByAttrScalar:
    def test_narrative_indexed_by_thread(self):
        n_intro = make_narrative("n_intro", thread="intro")
        n_main = make_narrative("n_main", thread="main")
        reg = DialogRegistry.build([n_intro, n_main])
        assert reg.get_by_attr("thread", "intro") == [n_intro]
        assert reg.get_by_attr("thread", "main") == [n_main]

    def test_multiple_narratives_same_thread(self):
        n1 = make_narrative("n1", thread="main", position=1)
        n2 = make_narrative("n2", thread="main", position=2)
        reg = DialogRegistry.build([n1, n2])
        result = reg.get_by_attr("thread", "main")
        assert set(d.dialog_id for d in result) == {"n1", "n2"}

    def test_functional_indexed_by_functional_type(self):
        greeting = make_functional("hello", functional_type="greeting")
        farewell = make_functional("bye", functional_type="farewell")
        reg = DialogRegistry.build([greeting, farewell])
        assert reg.get_by_attr("functional_type", "greeting") == [greeting]
        assert reg.get_by_attr("functional_type", "farewell") == [farewell]

    def test_missing_attr_returns_empty(self):
        reg = DialogRegistry.build([make_narrative("n1")])
        assert reg.get_by_attr("thread", "nonexistent") == []

    def test_unknown_attr_returns_empty(self):
        reg = DialogRegistry.build([make_narrative("n1")])
        assert reg.get_by_attr("no_such_attr", "value") == []


# ── get_by_attr — list-valued (topics) ───────────────────────────────────────

class TestGetByAttrList:
    def test_each_topic_element_indexed_individually(self):
        c = make_chitchat("c1", topics=["pizza", "food"])
        reg = DialogRegistry.build([c])
        assert reg.get_by_attr("topics", "pizza") == [c]
        assert reg.get_by_attr("topics", "food") == [c]

    def test_topic_match_returns_correct_dialogs(self):
        c_food = make_chitchat("c_food", topics=["pizza", "food"])
        c_travel = make_chitchat("c_travel", topics=["travel", "cities"])
        reg = DialogRegistry.build([c_food, c_travel])
        assert reg.get_by_attr("topics", "pizza") == [c_food]
        assert reg.get_by_attr("topics", "travel") == [c_travel]

    def test_topic_shared_by_multiple_dialogs(self):
        c1 = make_chitchat("c1", topics=["food", "cooking"])
        c2 = make_chitchat("c2", topics=["food", "restaurants"])
        reg = DialogRegistry.build([c1, c2])
        result = reg.get_by_attr("topics", "food")
        assert set(d.dialog_id for d in result) == {"c1", "c2"}

    def test_empty_topics_list_not_indexed(self):
        c = make_chitchat("c1", topics=[])
        reg = DialogRegistry.build([c])
        assert reg.get_by_attr("topics", "") == []


# ── load_dialog_registry ──────────────────────────────────────────────────────

class TestLoadDialogRegistry:
    def test_loads_single_json_file(self, tmp_path):
        f = tmp_path / "dialogs.json"
        f.write_text(json.dumps([
            {"id": "n1", "type": "narrative", "thread": "main", "position": 1, "moves": []},
        ]), encoding="utf-8")
        reg = load_dialog_registry(str(f))
        assert reg.get_by_id("n1") is not None

    def test_loads_directory_of_json_files(self, tmp_path):
        (tmp_path / "a.json").write_text(json.dumps([
            {"id": "n1", "type": "narrative", "thread": "main", "position": 1, "moves": []},
        ]), encoding="utf-8")
        (tmp_path / "b.json").write_text(json.dumps([
            {"id": "c1", "type": "chitchat", "topics": ["food"], "moves": []},
        ]), encoding="utf-8")
        reg = load_dialog_registry(str(tmp_path))
        assert reg.get_by_id("n1") is not None
        assert reg.get_by_id("c1") is not None

    def test_malformed_file_skipped_others_loaded(self, tmp_path, caplog):
        """A malformed JSON file must not abort loading of other files."""
        (tmp_path / "good.json").write_text(json.dumps([
            {"id": "n1", "type": "narrative", "thread": "main", "position": 1, "moves": []},
        ]), encoding="utf-8")
        (tmp_path / "bad.json").write_text("THIS IS NOT JSON", encoding="utf-8")
        import logging
        with caplog.at_level(logging.ERROR):
            reg = load_dialog_registry(str(tmp_path))
        assert reg.get_by_id("n1") is not None
        assert "bad.json" in caplog.text

    def test_invalid_dialog_spec_skipped(self, tmp_path, caplog):
        """A valid JSON file with an invalid dialog spec logs an error and skips that entry."""
        f = tmp_path / "mixed.json"
        f.write_text(json.dumps([
            {"id": "n1", "type": "narrative", "thread": "main", "position": 1, "moves": []},
            {"id": "bad", "type": "narrative"},  # missing required fields
        ]), encoding="utf-8")
        import logging
        with caplog.at_level(logging.ERROR):
            reg = load_dialog_registry(str(f))
        assert reg.get_by_id("n1") is not None

    def test_nonexistent_path_returns_empty_registry(self, caplog):
        import logging
        with caplog.at_level(logging.ERROR):
            reg = load_dialog_registry("/nonexistent/path/dialogs.json")
        assert len(reg) == 0

    def test_non_json_files_in_directory_ignored(self, tmp_path):
        (tmp_path / "notes.txt").write_text("not json", encoding="utf-8")
        (tmp_path / "dialogs.json").write_text(json.dumps([
            {"id": "n1", "type": "narrative", "thread": "main", "position": 1, "moves": []},
        ]), encoding="utf-8")
        reg = load_dialog_registry(str(tmp_path))
        assert len(reg) == 1
