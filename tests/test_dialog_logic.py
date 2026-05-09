"""Tests for DialogLogic — eligibility checking, interest matching, and session construction."""
import pytest

from nardial.dialog_logic import DialogLogic
from nardial.mini_dialogs import (
    MiniDialog, NarrativeDialog, ChitchatDialog, FunctionalDialog,
)
from nardial.moves import MoveSay


# ── helpers ───────────────────────────────────────────────────────────────────

def make_dialog(dialog_id, dependencies=None, variable_dependencies=None):
    return MiniDialog(
        dialog_id=dialog_id,
        moves=[MoveSay(text="hi")],
        dependencies=dependencies or [],
        variable_dependencies=variable_dependencies or [],
    )


def make_narrative(dialog_id, thread, position, dependencies=None, variable_dependencies=None):
    return NarrativeDialog(
        dialog_id=dialog_id,
        moves=[MoveSay(text="narrative")],
        thread=thread,
        position=position,
        dependencies=dependencies or [],
        variable_dependencies=variable_dependencies or [],
    )


def make_chitchat(dialog_id, topics=None, dependencies=None):
    return ChitchatDialog(
        dialog_id=dialog_id,
        moves=[MoveSay(text="chitchat")],
        topics=topics or [],
        dependencies=dependencies or [],
    )


def make_functional(dialog_id, functional_type="greeting"):
    return FunctionalDialog(
        dialog_id=dialog_id,
        moves=[MoveSay(text="hello")],
        type=functional_type,
    )


# ── is_dialog_eligible ────────────────────────────────────────────────────────

class TestIsDialogEligible:
    def test_eligible_with_no_constraints(self):
        dialog = make_dialog("d1")
        assert DialogLogic.is_dialog_eligible(dialog, completed_ids=[], user_model={})

    def test_already_completed_is_not_eligible(self):
        dialog = make_dialog("d1")
        assert not DialogLogic.is_dialog_eligible(dialog, completed_ids=["d1"], user_model={})

    def test_unsatisfied_dependency_blocks(self):
        dialog = make_dialog("d2", dependencies=["d1"])
        assert not DialogLogic.is_dialog_eligible(dialog, completed_ids=[], user_model={})

    def test_satisfied_dependency_allows(self):
        dialog = make_dialog("d2", dependencies=["d1"])
        assert DialogLogic.is_dialog_eligible(dialog, completed_ids=["d1"], user_model={})

    def test_multiple_dependencies_all_must_be_satisfied(self):
        dialog = make_dialog("d3", dependencies=["d1", "d2"])
        assert not DialogLogic.is_dialog_eligible(dialog, completed_ids=["d1"], user_model={})
        assert DialogLogic.is_dialog_eligible(dialog, completed_ids=["d1", "d2"], user_model={})

    def test_required_variable_missing_blocks(self):
        dialog = make_dialog("d1", variable_dependencies=[{"variable": "name", "required": True}])
        assert not DialogLogic.is_dialog_eligible(dialog, completed_ids=[], user_model={})

    def test_required_variable_present_allows(self):
        dialog = make_dialog("d1", variable_dependencies=[{"variable": "name", "required": True}])
        assert DialogLogic.is_dialog_eligible(dialog, completed_ids=[], user_model={"name": "Alice"})

    def test_optional_variable_missing_does_not_block(self):
        dialog = make_dialog("d1", variable_dependencies=[{"variable": "name", "required": False}])
        assert DialogLogic.is_dialog_eligible(dialog, completed_ids=[], user_model={})

    def test_narrative_blocked_by_earlier_position_in_same_thread(self):
        d1 = make_narrative("step_1", thread="main", position=1)
        d2 = make_narrative("step_2", thread="main", position=2)
        assert not DialogLogic.is_dialog_eligible(d2, completed_ids=[], user_model={}, all_dialogs=[d1, d2])

    def test_narrative_allowed_when_earlier_position_completed(self):
        d1 = make_narrative("step_1", thread="main", position=1)
        d2 = make_narrative("step_2", thread="main", position=2)
        assert DialogLogic.is_dialog_eligible(d2, completed_ids=["step_1"], user_model={}, all_dialogs=[d1, d2])

    def test_narrative_different_threads_do_not_block_each_other(self):
        d_a = make_narrative("thread_a_1", thread="a", position=1)
        d_b = make_narrative("thread_b_1", thread="b", position=1)
        assert DialogLogic.is_dialog_eligible(d_b, completed_ids=[], user_model={}, all_dialogs=[d_a, d_b])

    def test_all_dialogs_none_does_not_crash_narrative_check(self):
        d = make_narrative("n1", thread="main", position=2)
        # Should not raise; treats all_dialogs as empty
        result = DialogLogic.is_dialog_eligible(d, completed_ids=[], user_model={}, all_dialogs=None)
        assert result is True


# ── matches_user_interests ────────────────────────────────────────────────────

class TestMatchesUserInterests:
    def test_always_matches_when_no_interests(self):
        dialog = make_chitchat("c1", topics=["cats", "dogs"])
        assert DialogLogic.matches_user_interests(dialog, topics_of_interest=[])

    def test_matches_when_topic_overlaps(self):
        dialog = make_chitchat("c1", topics=["cats"])
        assert DialogLogic.matches_user_interests(dialog, topics_of_interest=["Cats", "dogs"])

    def test_no_match_when_no_topic_overlap(self):
        dialog = make_chitchat("c1", topics=["birds"])
        assert not DialogLogic.matches_user_interests(dialog, topics_of_interest=["cats", "dogs"])

    def test_case_insensitive_comparison(self):
        dialog = make_chitchat("c1", topics=["DOGS"])
        assert DialogLogic.matches_user_interests(dialog, topics_of_interest=["dogs"])

    def test_dialog_with_no_topics_does_not_match_when_interests_set(self):
        dialog = make_chitchat("c1", topics=[])
        assert not DialogLogic.matches_user_interests(dialog, topics_of_interest=["cats"])


# ── sort_chitchat_dialogs ─────────────────────────────────────────────────────

class TestSortChitchatDialogs:
    def test_returns_empty_for_no_candidates(self):
        assert DialogLogic.sort_chitchat_dialogs([]) == []

    def test_interest_matched_dialog_scores_higher(self):
        c_interested = make_chitchat("c_int", topics=["cats"])
        c_plain = make_chitchat("c_plain", topics=[])
        result = DialogLogic.sort_chitchat_dialogs([c_plain, c_interested], topics_of_interest=["cats"])
        assert result[0] == c_interested

    def test_excludes_non_chitchat_dialogs(self):
        narrative = make_narrative("n1", thread="main", position=1)
        c1 = make_chitchat("c1")
        result = DialogLogic.sort_chitchat_dialogs([narrative, c1])
        assert narrative not in result
        assert c1 in result

    def test_returns_all_chitchat_dialogs(self):
        c1 = make_chitchat("c1", topics=["food"])
        c2 = make_chitchat("c2", topics=["travel"])
        result = DialogLogic.sort_chitchat_dialogs([c1, c2])
        assert len(result) == 2


# ── select_next_narrative ─────────────────────────────────────────────────────

class TestSelectNextNarrative:
    def test_returns_lowest_position_eligible(self):
        d1 = make_narrative("n1", thread="main", position=1)
        d2 = make_narrative("n2", thread="main", position=2)
        result = DialogLogic.select_next_narrative(
            [d1, d2], "main", completed_ids=[], user_model={}, all_dialogs=[d1, d2]
        )
        assert result == d1

    def test_skips_completed_dialogs(self):
        d1 = make_narrative("n1", thread="main", position=1)
        d2 = make_narrative("n2", thread="main", position=2)
        result = DialogLogic.select_next_narrative(
            [d1, d2], "main", completed_ids=["n1"], user_model={}, all_dialogs=[d1, d2]
        )
        assert result == d2

    def test_returns_none_when_thread_exhausted(self):
        d1 = make_narrative("n1", thread="main", position=1)
        result = DialogLogic.select_next_narrative(
            [d1], "main", completed_ids=["n1"], user_model={}, all_dialogs=[d1]
        )
        assert result is None

    def test_ignores_other_threads(self):
        d_b = make_narrative("n_b", thread="b", position=1)
        result = DialogLogic.select_next_narrative(
            [d_b], "a", completed_ids=[], user_model={}, all_dialogs=[d_b]
        )
        assert result is None


# ── select_active_thread ──────────────────────────────────────────────────────

class TestSelectActiveThread:
    def _pool(self):
        return [
            make_narrative("n_main_1", "main", 1),
            make_narrative("n_main_2", "main", 2),
            make_narrative("n_side_1", "side", 1),
        ]

    def test_returns_preferred_thread_when_it_has_runnable_dialogs(self):
        pool = self._pool()
        thread = DialogLogic.select_active_thread(pool, "main", completed_ids=set(), user_model={})
        assert thread == "main"

    def test_returns_preferred_thread_when_partial_completion(self):
        pool = self._pool()
        # Only the first main dialog is done; main still has n_main_2 available.
        thread = DialogLogic.select_active_thread(
            pool, "main", completed_ids={"n_main_1"}, user_model={}
        )
        assert thread == "main"

    def test_falls_back_to_another_thread_when_preferred_is_exhausted(self):
        pool = self._pool()
        thread = DialogLogic.select_active_thread(
            pool, "main", completed_ids={"n_main_1", "n_main_2"}, user_model={}
        )
        assert thread == "side"

    def test_returns_none_when_all_threads_exhausted(self):
        pool = self._pool()
        thread = DialogLogic.select_active_thread(
            pool, "main",
            completed_ids={"n_main_1", "n_main_2", "n_side_1"},
            user_model={},
        )
        assert thread is None

    def test_returns_none_when_no_narrative_dialogs(self):
        pool = [make_functional("greeting"), make_functional("farewell", "farewell")]
        thread = DialogLogic.select_active_thread(pool, "main", completed_ids=set(), user_model={})
        assert thread is None

    def test_none_preferred_thread_returns_any_available(self):
        pool = self._pool()
        thread = DialogLogic.select_active_thread(pool, None, completed_ids=set(), user_model={})
        assert thread in {"main", "side"}
