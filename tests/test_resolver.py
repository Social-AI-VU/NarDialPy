"""Tests for resolve_agenda() and AgendaContext.mark_completed()."""

import logging

import pytest

from nardial.agenda import (
    AgendaContext,
    ChitchatSlot,
    DialogRef,
    FunctionalSlot,
    LLMDialogRef,
    NarrativeSlot,
    SlotBounds,
    resolve_agenda,
)
from nardial.agenda.resolver import _should_requeue
from nardial.dialog_registry import DialogRegistry
from nardial.mini_dialogs import (
    ChitchatDialog,
    FunctionalDialog,
    LLMMiniDialog,
    NarrativeDialog,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_registry(*dialogs):
    return DialogRegistry.build(list(dialogs))


def make_context(registry=None, completed_ids=None, topics_of_interest=None):
    return AgendaContext(
        registry=registry or make_registry(),
        completed_ids=set(completed_ids or []),
        topics_of_interest=topics_of_interest or [],
    )


def make_narrative(dialog_id, thread="main", position=1, dependencies=None):
    return NarrativeDialog(
        dialog_id=dialog_id, moves=[], thread=thread, position=position,
        dependencies=dependencies or [],
    )


def make_chitchat(dialog_id, topics=None):
    return ChitchatDialog(dialog_id=dialog_id, moves=[], topics=topics or [])


def make_functional(dialog_id, functional_type="greeting"):
    return FunctionalDialog(dialog_id=dialog_id, moves=[], functional_type=functional_type)


def make_llm(dialog_id):
    return LLMMiniDialog(dialog_id=dialog_id, prompt="Chat.")


def collect_with_context(items, context):
    """Run resolve_agenda to completion, calling mark_completed after each dialog."""
    results = []
    for dialog in resolve_agenda(items, context):
        results.append(dialog)
        context.mark_completed(dialog.dialog_id)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# AgendaContext.mark_completed
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkCompleted:
    def test_adds_to_completed_ids(self):
        ctx = make_context()
        ctx.mark_completed("n1")
        assert "n1" in ctx.completed_ids

    def test_adds_to_session_completed_ids(self):
        ctx = make_context()
        ctx.mark_completed("n1")
        assert "n1" in ctx.session_completed_ids

    def test_both_sets_updated(self):
        ctx = make_context()
        ctx.mark_completed("a")
        ctx.mark_completed("b")
        assert ctx.completed_ids == {"a", "b"}
        assert ctx.session_completed_ids == {"a", "b"}

    def test_idempotent(self):
        ctx = make_context()
        ctx.mark_completed("n1")
        ctx.mark_completed("n1")
        assert ctx.completed_ids == {"n1"}

    def test_does_not_affect_pre_existing_completed_ids(self):
        ctx = make_context(completed_ids=["old"])
        ctx.mark_completed("new")
        assert "old" in ctx.completed_ids
        assert "new" in ctx.completed_ids
        # pre-existing id is in completed_ids but NOT session_completed_ids
        assert "old" not in ctx.session_completed_ids


# ─────────────────────────────────────────────────────────────────────────────
# _should_requeue unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestShouldRequeue:
    def test_default_bounds_stops_after_one(self):
        # SlotBounds() = count_min=1, count_max=1
        assert not _should_requeue(SlotBounds(), dialogs_run=1, elapsed=0.0)

    def test_below_count_min_must_requeue(self):
        assert _should_requeue(SlotBounds(count_min=3, count_max=None), dialogs_run=2, elapsed=0.0)

    def test_above_count_max_stops(self):
        assert not _should_requeue(SlotBounds(count_min=1, count_max=3), dialogs_run=3, elapsed=0.0)

    def test_unlimited_count_max_requeues(self):
        assert _should_requeue(SlotBounds(count_min=1, count_max=None), dialogs_run=100, elapsed=0.0)

    def test_duration_max_is_hard_ceiling(self):
        # Even though count_min not yet satisfied, duration_max overrides.
        assert not _should_requeue(
            SlotBounds(count_min=5, count_max=None, duration_max=10.0),
            dialogs_run=1,
            elapsed=11.0,
        )

    def test_duration_min_forces_requeue(self):
        # dialogs_run >= count_min but duration_min not yet met → keep going
        assert _should_requeue(
            SlotBounds(count_min=1, count_max=None, duration_min=60.0),
            dialogs_run=1,
            elapsed=30.0,
        )

    def test_duration_min_satisfied_stops_when_count_max_reached(self):
        assert not _should_requeue(
            SlotBounds(count_min=1, count_max=2, duration_min=10.0),
            dialogs_run=2,
            elapsed=15.0,
        )

    def test_within_range_continues(self):
        assert _should_requeue(
            SlotBounds(count_min=2, count_max=4),
            dialogs_run=2,
            elapsed=0.0,
        )


# ─────────────────────────────────────────────────────────────────────────────
# resolve_agenda — basic ordering
# ─────────────────────────────────────────────────────────────────────────────

class TestResolveAgendaOrdering:
    def test_empty_agenda_yields_nothing(self):
        ctx = make_context()
        assert collect_with_context([], ctx) == []

    def test_single_string_item(self):
        n = make_narrative("n1")
        ctx = make_context(registry=make_registry(n))
        results = collect_with_context(["n1"], ctx)
        assert [d.dialog_id for d in results] == ["n1"]

    def test_flat_list_preserves_order(self):
        n1 = make_narrative("n1", thread="a", position=1)
        n2 = make_narrative("n2", thread="b", position=1)
        reg = make_registry(n1, n2)
        ctx = make_context(registry=reg)
        results = collect_with_context(
            [DialogRef(id="n1"), DialogRef(id="n2")], ctx
        )
        assert [d.dialog_id for d in results] == ["n1", "n2"]

    def test_unknown_id_skipped_silently(self, caplog):
        ctx = make_context()
        with caplog.at_level(logging.WARNING):
            results = collect_with_context(["nonexistent"], ctx)
        assert results == []

    def test_none_resolving_item_skipped(self):
        # An empty thread → NarrativeSlot returns None → skipped
        ctx = make_context(registry=make_registry())
        results = collect_with_context(
            [NarrativeSlot(thread="empty")], ctx
        )
        assert results == []

    def test_mixed_none_and_valid(self):
        n = make_narrative("n1")
        ctx = make_context(registry=make_registry(n))
        results = collect_with_context(
            [NarrativeSlot(thread="ghost"), DialogRef(id="n1")], ctx
        )
        assert [d.dialog_id for d in results] == ["n1"]


# ─────────────────────────────────────────────────────────────────────────────
# resolve_agenda — incremental context update (core architecture test)
# ─────────────────────────────────────────────────────────────────────────────

class TestResolveAgendaIncremental:
    def test_narrative_slot_second_step_needs_first_completed(self):
        """The resolver must select n2 only AFTER n1 is marked complete.

        NarrativeOrderingRule blocks n2 (position=2) until n1 (position=1) is
        in completed_ids.  This verifies the incremental re-queue pattern.
        """
        n1 = make_narrative("n1", thread="main", position=1)
        n2 = make_narrative("n2", thread="main", position=2)
        reg = make_registry(n1, n2)
        ctx = make_context(registry=reg)
        slot = NarrativeSlot(thread="main", bounds=SlotBounds(count_min=2, count_max=2))

        gen = resolve_agenda([slot], ctx)

        first = next(gen)
        assert first is n1
        # n2 still blocked — n1 not yet completed
        assert "n1" not in ctx.completed_ids

        ctx.mark_completed("n1")

        second = next(gen)
        assert second is n2

        with pytest.raises(StopIteration):
            next(gen)

    def test_completed_ids_updated_between_resolutions(self):
        n1 = make_narrative("n1", thread="t", position=1)
        n2 = make_narrative("n2", thread="t", position=2)
        reg = make_registry(n1, n2)
        ctx = make_context(registry=reg)

        results = collect_with_context(
            [NarrativeSlot(thread="t", bounds=SlotBounds(count_min=2, count_max=2))],
            ctx,
        )
        assert [d.dialog_id for d in results] == ["n1", "n2"]
        assert ctx.completed_ids == {"n1", "n2"}

    def test_session_completed_ids_also_updated(self):
        n1 = make_narrative("n1")
        reg = make_registry(n1)
        ctx = make_context(registry=reg)
        collect_with_context(["n1"], ctx)
        assert "n1" in ctx.session_completed_ids


# ─────────────────────────────────────────────────────────────────────────────
# resolve_agenda — SlotBounds count
# ─────────────────────────────────────────────────────────────────────────────

class TestResolveAgendaCountBounds:
    def test_count_max_limits_resolutions(self):
        # Three chitchat dialogs, count_max=2 → only 2 should run
        c1 = make_chitchat("c1")
        c2 = make_chitchat("c2")
        c3 = make_chitchat("c3")
        reg = make_registry(c1, c2, c3)
        ctx = make_context(registry=reg)
        results = collect_with_context(
            [ChitchatSlot(bounds=SlotBounds(count_min=1, count_max=2))], ctx
        )
        assert len(results) == 2

    def test_count_min_2_runs_twice(self):
        c1 = make_chitchat("c1")
        c2 = make_chitchat("c2")
        reg = make_registry(c1, c2)
        ctx = make_context(registry=reg)
        results = collect_with_context(
            [ChitchatSlot(bounds=SlotBounds(count_min=2, count_max=2))], ctx
        )
        assert len(results) == 2

    def test_pool_exhaustion_before_count_min_warns(self, caplog):
        # Only 1 dialog in pool, count_min=3
        c1 = make_chitchat("c1")
        reg = make_registry(c1)
        ctx = make_context(registry=reg)
        with caplog.at_level(logging.WARNING):
            results = collect_with_context(
                [ChitchatSlot(bounds=SlotBounds(count_min=3, count_max=None))], ctx
            )
        assert len(results) == 1
        assert "count_min=3" in caplog.text

    def test_unlimited_count_max_runs_until_pool_exhausted(self):
        c1 = make_chitchat("c1")
        c2 = make_chitchat("c2")
        reg = make_registry(c1, c2)
        ctx = make_context(registry=reg)
        results = collect_with_context(
            [ChitchatSlot(bounds=SlotBounds(count_min=1, count_max=None))], ctx
        )
        assert len(results) == 2

    def test_default_bounds_runs_exactly_once(self):
        c1 = make_chitchat("c1")
        c2 = make_chitchat("c2")
        reg = make_registry(c1, c2)
        ctx = make_context(registry=reg)
        results = collect_with_context([ChitchatSlot()], ctx)
        assert len(results) == 1

    def test_multiple_slots_run_independently(self):
        n1 = make_narrative("n1", thread="intro", position=1)
        f1 = make_functional("greet", functional_type="greeting")
        reg = make_registry(n1, f1)
        ctx = make_context(registry=reg)
        results = collect_with_context(
            [
                FunctionalSlot(functional_type="greeting"),
                NarrativeSlot(thread="intro"),
            ],
            ctx,
        )
        assert len(results) == 2
        assert results[0].dialog_id == "greet"
        assert results[1].dialog_id == "n1"


# ─────────────────────────────────────────────────────────────────────────────
# resolve_agenda — dict / mixed input coercion
# ─────────────────────────────────────────────────────────────────────────────

class TestResolveAgendaCoercion:
    def test_string_items_coerced(self):
        n = make_narrative("n1")
        ctx = make_context(registry=make_registry(n))
        results = collect_with_context(["n1"], ctx)
        assert results[0].dialog_id == "n1"

    def test_dict_items_coerced(self):
        n = make_narrative("n1")
        ctx = make_context(registry=make_registry(n))
        results = collect_with_context(
            [{"type": "dialog_ref", "id": "n1"}], ctx
        )
        assert results[0].dialog_id == "n1"

    def test_agenda_item_objects_accepted(self):
        n = make_narrative("n1")
        ctx = make_context(registry=make_registry(n))
        results = collect_with_context([DialogRef(id="n1")], ctx)
        assert results[0].dialog_id == "n1"

    def test_llm_dialog_ref_in_agenda(self):
        llm = make_llm("chat")
        ctx = make_context(registry=make_registry(llm))
        results = collect_with_context(
            [LLMDialogRef(id="chat")], ctx
        )
        assert results[0].dialog_id == "chat"
