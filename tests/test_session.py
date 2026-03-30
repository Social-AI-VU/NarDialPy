"""Tests for the Dialog and Session abstractions in src/session.py."""
import sys
import os

import pytest
from unittest.mock import Mock

# Add project root so that `from src.xxx import ...` resolves to the same module
# objects that dialog.py uses (which also uses `src.`-prefixed imports internally).
# Without this, `mini_dialogs` and `src.mini_dialogs` would be two distinct modules
# in Python's module cache, causing isinstance() checks in DialogLogic to silently
# fail (e.g. isinstance(d, NarrativeDialog) would return False for objects created
# in this test file).
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# Keep src/ on path so conftest fixtures continue to work
SRC_DIR = os.path.join(PROJECT_ROOT, 'src')
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from src.mini_dialogs import NarrativeDialog, ChitchatDialog, FunctionalDialog
from src.moves import MOVE_SAY
from src.dialog import DialogLogic
from src.session import Dialog, Session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _narrative(dialog_id, thread="t1", position=1, dependencies=None):
    moves = [{"type": MOVE_SAY, "text": f"[{dialog_id}]"}]
    return NarrativeDialog(dialog_id, moves, thread=thread, position=position, dependencies=dependencies or [])


def _chitchat(dialog_id, theme="nature", topics=None, dependencies=None):
    moves = [{"type": MOVE_SAY, "text": f"[{dialog_id}]"}]
    return ChitchatDialog(dialog_id, moves, theme=theme, topics=topics or [], dependencies=dependencies or [])


def _functional(dialog_id, ftype="greeting"):
    moves = [{"type": MOVE_SAY, "text": f"[{dialog_id}]"}]
    return FunctionalDialog(dialog_id, moves, type=ftype)


def _mock_agent():
    agent = Mock()
    agent.say = Mock()
    return agent


# ---------------------------------------------------------------------------
# Dialog tests
# ---------------------------------------------------------------------------

class TestDialog:
    def test_iter_and_len(self):
        n1 = _narrative("n1")
        n2 = _narrative("n2", position=2)
        d = Dialog([n1, n2], thread="t1", theme="nature")

        assert len(d) == 2
        assert list(d) == [n1, n2]

    def test_empty_dialog(self):
        d = Dialog([])
        assert len(d) == 0
        assert list(d) == []

    def test_repr_contains_metadata(self):
        n1 = _narrative("n1")
        d = Dialog([n1], thread="t1", theme="nature")
        r = repr(d)
        assert "t1" in r
        assert "nature" in r
        assert "n1" in r

    def test_defaults_are_none(self):
        d = Dialog([])
        assert d.thread is None
        assert d.theme is None

    def test_mini_dialogs_copied(self):
        n1 = _narrative("n1")
        source = [n1]
        d = Dialog(source)
        source.clear()
        # Dialog keeps its own copy
        assert len(d) == 1


# ---------------------------------------------------------------------------
# Session tests
# ---------------------------------------------------------------------------

class TestSession:
    def test_initial_state(self):
        d = Dialog([_narrative("n1")])
        s = Session(d, completed_dialogs={"prev"}, user_model={"age": 9}, topics_of_interest=["robots"])
        assert "prev" in s.completed_dialogs
        assert s.user_model == {"age": 9}
        assert s.topics_of_interest == ["robots"]
        assert s.history == []
        assert s.executed_dialog_ids == []

    def test_defaults_are_empty(self):
        d = Dialog([])
        s = Session(d)
        assert s.completed_dialogs == set()
        assert s.user_model == {}
        assert s.topics_of_interest == []

    def test_run_executes_dialogs_and_records_history(self):
        n1 = _narrative("n1")
        n2 = _narrative("n2", position=2, dependencies=["n1"])
        d = Dialog([n1, n2])
        s = Session(d)
        agent = _mock_agent()

        history = s.run(agent, all_dialogs=[n1, n2])

        assert s.executed_dialog_ids == ["n1", "n2"]
        assert "n1" in s.completed_dialogs
        assert "n2" in s.completed_dialogs
        types = [e["type"] for e in history]
        assert types.count("dialog_start") == 2
        assert types.count("dialog_end") == 2

    def test_run_returns_same_list_as_history_attribute(self):
        d = Dialog([_narrative("n1")])
        s = Session(d)
        returned = s.run(_mock_agent())
        assert returned is s.history

    def test_run_skips_dialogs_with_unmet_dependencies(self):
        n1 = _narrative("n1")
        n2 = _narrative("n2", position=2, dependencies=["n1"])
        # n1 excluded from dialog; n2 cannot run without it
        d = Dialog([n2])
        s = Session(d, completed_dialogs=set())
        agent = _mock_agent()

        s.run(agent, all_dialogs=[n1, n2])

        assert s.executed_dialog_ids == []
        assert "n2" not in s.completed_dialogs

    def test_run_skips_already_completed(self):
        n1 = _narrative("n1")
        d = Dialog([n1])
        # n1 already in completed_dialogs
        s = Session(d, completed_dialogs={"n1"})
        s.run(_mock_agent(), all_dialogs=[n1])
        assert s.executed_dialog_ids == []

    def test_run_updates_topics_of_interest(self):
        """MiniDialog.run() updates topics_of_interest in place; Session reflects that."""
        n1 = _narrative("n1")
        d = Dialog([n1])
        s = Session(d, topics_of_interest=["space"])

        def fake_run(agent, history, topics, user_model):
            topics.append("robots")

        n1.run = fake_run
        s.run(_mock_agent())
        assert "robots" in s.topics_of_interest

    def test_run_updates_user_model(self):
        n1 = _narrative("n1")
        d = Dialog([n1])
        s = Session(d, user_model={"age": 9})

        def fake_run(agent, history, topics, user_model):
            user_model["name"] = "Alice"

        n1.run = fake_run
        s.run(_mock_agent())
        assert s.user_model["name"] == "Alice"


# ---------------------------------------------------------------------------
# DialogLogic.build_dialog tests
# ---------------------------------------------------------------------------

class TestBuildDialog:
    def test_returns_dialog_instance(self):
        greeting = _functional("greet", "greeting")
        n1 = _narrative("n1", thread="t1", position=1)
        farewell = _functional("bye", "farewell")
        all_dialogs = [greeting, n1, farewell]
        result = DialogLogic.build_dialog(all_dialogs, thread="t1")
        assert isinstance(result, Dialog)

    def test_thread_and_theme_set(self):
        greeting = _functional("greet", "greeting")
        n1 = _narrative("n1", thread="t1", position=1)
        farewell = _functional("bye", "farewell")
        result = DialogLogic.build_dialog([greeting, n1, farewell], thread="t1", theme="nature")
        assert result.theme == "nature"

    def test_completed_ids_exclude_dialogs(self):
        greeting = _functional("greet", "greeting")
        n1 = _narrative("n1", thread="t1", position=1)
        n2 = _narrative("n2", thread="t1", position=2, dependencies=["n1"])
        farewell = _functional("bye", "farewell")
        all_dialogs = [greeting, n1, n2, farewell]
        # n1 already completed → n2 should be selected instead
        result = DialogLogic.build_dialog(all_dialogs, thread="t1", completed_ids={"n1"})
        ids = [d.dialog_id for d in result]
        assert "n1" not in ids
        assert "n2" in ids

    def test_empty_catalog_returns_empty_dialog(self):
        result = DialogLogic.build_dialog([])
        assert isinstance(result, Dialog)
        assert len(result) == 0
