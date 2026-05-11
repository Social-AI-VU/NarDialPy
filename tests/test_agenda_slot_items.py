"""Tests for NarrativeSlot, ChitchatSlot, FunctionalSlot, and LLMDialogRef."""

import random
import logging

import pytest
from pydantic import ValidationError

from nardial.agenda import (
    AgendaContext,
    AnyAgendaItem,
    ChitchatSlot,
    FunctionalSlot,
    LLMDialogRef,
    NarrativeSlot,
    SlotBounds,
    to_agenda_item,
)
from nardial.dialog_registry import DialogRegistry
from nardial.eligibility import EligibilityPolicy, ExcludeIfSeenRule, DepsMetRule
from nardial.mini_dialogs import (
    ChitchatDialog,
    FunctionalDialog,
    LLMMiniDialog,
    NarrativeDialog,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_registry(*dialogs):
    return DialogRegistry.build(list(dialogs))


def make_context(
    registry=None,
    completed_ids=None,
    session_completed_ids=None,
    user_model=None,
    topics_of_interest=None,
):
    return AgendaContext(
        registry=registry or make_registry(),
        completed_ids=set(completed_ids or []),
        session_completed_ids=set(session_completed_ids or []),
        user_model=user_model or {},
        topics_of_interest=topics_of_interest or [],
    )


def make_narrative(dialog_id, thread="main", position=1, dependencies=None):
    return NarrativeDialog(
        dialog_id=dialog_id,
        moves=[],
        thread=thread,
        position=position,
        dependencies=dependencies or [],
    )


def make_chitchat(dialog_id, topics=None, dependencies=None):
    return ChitchatDialog(
        dialog_id=dialog_id,
        moves=[],
        topics=topics or [],
        dependencies=dependencies or [],
    )


def make_functional(dialog_id, functional_type="greeting"):
    return FunctionalDialog(dialog_id=dialog_id, moves=[], functional_type=functional_type)


def make_llm(dialog_id, max_turns=None, duration=None):
    return LLMMiniDialog(dialog_id=dialog_id, prompt="Chat.", max_turns=max_turns, duration=duration)


# ─────────────────────────────────────────────────────────────────────────────
# NarrativeSlot
# ─────────────────────────────────────────────────────────────────────────────

class TestNarrativeSlotConstruction:
    def test_type_literal(self):
        assert NarrativeSlot(thread="intro").type == "narrative_slot"

    def test_thread_stored(self):
        s = NarrativeSlot(thread="intro")
        assert s.thread == "intro"

    def test_default_bounds_is_exactly_once(self):
        s = NarrativeSlot(thread="intro")
        assert s.bounds == SlotBounds()

    def test_custom_bounds(self):
        s = NarrativeSlot(thread="intro", bounds=SlotBounds(count_min=2, count_max=4))
        assert s.bounds.count_min == 2

    def test_eligibility_policy_defaults_none(self):
        assert NarrativeSlot(thread="intro").eligibility_policy is None

    def test_eligibility_policy_excluded_from_serialisation(self):
        policy = EligibilityPolicy([ExcludeIfSeenRule()])
        s = NarrativeSlot(thread="intro", eligibility_policy=policy)
        assert "eligibility_policy" not in s.model_dump()

    def test_from_dict(self):
        s = NarrativeSlot.model_validate({"type": "narrative_slot", "thread": "main"})
        assert s.thread == "main"

    def test_thread_required(self):
        with pytest.raises(ValidationError):
            NarrativeSlot.model_validate({"type": "narrative_slot"})


class TestNarrativeSlotResolve:
    def test_returns_only_eligible_dialog(self):
        n1 = make_narrative("n1", thread="intro", position=1)
        ctx = make_context(registry=make_registry(n1))
        result = NarrativeSlot(thread="intro").resolve(ctx)
        assert result is n1

    def test_returns_lowest_position(self):
        n1 = make_narrative("n1", thread="intro", position=1)
        n2 = make_narrative("n2", thread="intro", position=2)
        ctx = make_context(registry=make_registry(n1, n2))
        result = NarrativeSlot(thread="intro").resolve(ctx)
        assert result is n1

    def test_skips_completed_dialog(self):
        n1 = make_narrative("n1", thread="intro", position=1)
        n2 = make_narrative("n2", thread="intro", position=2)
        ctx = make_context(registry=make_registry(n1, n2), completed_ids=["n1"])
        result = NarrativeSlot(thread="intro").resolve(ctx)
        assert result is n2

    def test_random_tiebreak_at_same_position(self):
        # Two dialogs at position 1 — over many draws both should appear.
        a = make_narrative("a", thread="intro", position=1)
        b = make_narrative("b", thread="intro", position=1)
        reg = make_registry(a, b)
        random.seed(42)
        results = {
            NarrativeSlot(thread="intro").resolve(make_context(registry=reg)).dialog_id
            for _ in range(30)
        }
        assert results == {"a", "b"}

    def test_returns_none_when_thread_empty(self, caplog):
        ctx = make_context(registry=make_registry())
        with caplog.at_level(logging.WARNING):
            result = NarrativeSlot(thread="missing").resolve(ctx)
        assert result is None
        assert "missing" in caplog.text

    def test_returns_none_when_all_completed(self, caplog):
        n1 = make_narrative("n1", thread="intro", position=1)
        ctx = make_context(registry=make_registry(n1), completed_ids=["n1"])
        with caplog.at_level(logging.WARNING):
            result = NarrativeSlot(thread="intro").resolve(ctx)
        assert result is None

    def test_respects_custom_eligibility_policy(self):
        # Custom policy that blocks everything — resolve should return None.
        n1 = make_narrative("n1", thread="intro", position=1)
        ctx = make_context(registry=make_registry(n1))
        block_all = EligibilityPolicy([ExcludeIfSeenRule()])
        result = NarrativeSlot(
            thread="intro",
            eligibility_policy=block_all,
        ).resolve(make_context(registry=make_registry(n1), completed_ids=["n1"]))
        assert result is None

    def test_different_threads_do_not_interfere(self):
        a1 = make_narrative("a1", thread="arc_a", position=1)
        b1 = make_narrative("b1", thread="arc_b", position=1)
        reg = make_registry(a1, b1)
        ctx = make_context(registry=reg)
        assert NarrativeSlot(thread="arc_a").resolve(ctx) is a1
        assert NarrativeSlot(thread="arc_b").resolve(ctx) is b1


# ─────────────────────────────────────────────────────────────────────────────
# ChitchatSlot
# ─────────────────────────────────────────────────────────────────────────────

class TestChitchatSlotConstruction:
    def test_type_literal(self):
        assert ChitchatSlot().type == "chitchat_slot"

    def test_default_bounds_is_exactly_once(self):
        assert ChitchatSlot().bounds == SlotBounds()

    def test_topics_filter_defaults_none(self):
        assert ChitchatSlot().topics_filter is None

    def test_eligibility_policy_excluded_from_serialisation(self):
        s = ChitchatSlot(eligibility_policy=EligibilityPolicy([]))
        assert "eligibility_policy" not in s.model_dump()

    def test_from_dict(self):
        s = ChitchatSlot.model_validate({"type": "chitchat_slot"})
        assert s.topics_filter is None


class TestChitchatSlotResolve:
    def test_returns_eligible_dialog(self):
        c1 = make_chitchat("c1", topics=["food"])
        ctx = make_context(registry=make_registry(c1))
        assert ChitchatSlot().resolve(ctx) is c1

    def test_returns_none_when_no_candidates(self, caplog):
        ctx = make_context(registry=make_registry())
        with caplog.at_level(logging.WARNING):
            result = ChitchatSlot().resolve(ctx)
        assert result is None
        assert "no eligible" in caplog.text

    def test_returns_none_when_all_seen(self, caplog):
        c1 = make_chitchat("c1", topics=["food"])
        ctx = make_context(registry=make_registry(c1), completed_ids=["c1"])
        with caplog.at_level(logging.WARNING):
            result = ChitchatSlot().resolve(ctx)
        assert result is None

    def test_ranks_by_topic_overlap(self):
        c_food = make_chitchat("c_food", topics=["food", "cooking"])
        c_sport = make_chitchat("c_sport", topics=["sport", "running"])
        reg = make_registry(c_food, c_sport)
        ctx = make_context(registry=reg, topics_of_interest=["food", "cooking"])
        result = ChitchatSlot().resolve(ctx)
        assert result is c_food

    def test_topics_filter_restricts_candidates(self):
        c_food = make_chitchat("c_food", topics=["food"])
        c_sport = make_chitchat("c_sport", topics=["sport"])
        reg = make_registry(c_food, c_sport)
        ctx = make_context(registry=reg)
        result = ChitchatSlot(topics_filter=["food"]).resolve(ctx)
        assert result is c_food

    def test_topics_filter_returns_none_when_no_match(self, caplog):
        c_food = make_chitchat("c_food", topics=["food"])
        reg = make_registry(c_food)
        ctx = make_context(registry=reg)
        with caplog.at_level(logging.WARNING):
            result = ChitchatSlot(topics_filter=["sport"]).resolve(ctx)
        assert result is None

    def test_equal_score_candidates_shuffled_randomly(self):
        # Three dialogs with no user interests → all score 0; all should appear over many draws.
        c1 = make_chitchat("c1", topics=["a"])
        c2 = make_chitchat("c2", topics=["b"])
        c3 = make_chitchat("c3", topics=["c"])
        reg = make_registry(c1, c2, c3)
        random.seed(0)
        seen = set()
        for _ in range(50):
            ctx = make_context(registry=reg)
            seen.add(ChitchatSlot().resolve(ctx).dialog_id)
        assert seen == {"c1", "c2", "c3"}

    def test_uses_real_user_model_for_variable_deps(self):
        # A chitchat dialog with a required variable dep should be blocked
        # when the variable is absent.
        c = ChitchatDialog(
            dialog_id="c_var",
            moves=[],
            topics=["food"],
            variable_dependencies=[{"variable": "age", "required": True}],
        )
        ctx = make_context(registry=make_registry(c), user_model={})
        assert ChitchatSlot().resolve(ctx) is None

        ctx_with_var = make_context(registry=make_registry(c), user_model={"age": "30"})
        assert ChitchatSlot().resolve(ctx_with_var) is c


# ─────────────────────────────────────────────────────────────────────────────
# FunctionalSlot
# ─────────────────────────────────────────────────────────────────────────────

class TestFunctionalSlotConstruction:
    def test_type_literal(self):
        assert FunctionalSlot(functional_type="greeting").type == "functional_slot"

    def test_functional_type_stored(self):
        assert FunctionalSlot(functional_type="farewell").functional_type == "farewell"

    def test_default_bounds_is_exactly_once(self):
        assert FunctionalSlot(functional_type="greeting").bounds == SlotBounds()

    def test_eligibility_policy_excluded_from_serialisation(self):
        s = FunctionalSlot(functional_type="greeting", eligibility_policy=EligibilityPolicy([]))
        assert "eligibility_policy" not in s.model_dump()

    def test_functional_type_required(self):
        with pytest.raises(ValidationError):
            FunctionalSlot.model_validate({"type": "functional_slot"})


class TestFunctionalSlotResolve:
    def test_returns_matching_functional_dialog(self):
        f = make_functional("greet", functional_type="greeting")
        ctx = make_context(registry=make_registry(f))
        assert FunctionalSlot(functional_type="greeting").resolve(ctx) is f

    def test_returns_none_when_no_match(self, caplog):
        ctx = make_context(registry=make_registry())
        with caplog.at_level(logging.WARNING):
            result = FunctionalSlot(functional_type="greeting").resolve(ctx)
        assert result is None
        assert "greeting" in caplog.text

    def test_returns_none_for_wrong_type(self, caplog):
        f = make_functional("bye", functional_type="farewell")
        ctx = make_context(registry=make_registry(f))
        with caplog.at_level(logging.WARNING):
            result = FunctionalSlot(functional_type="greeting").resolve(ctx)
        assert result is None

    def test_reruns_after_completion_by_default(self):
        # FunctionalDialog has no ExcludeIfSeenRule — it should resolve even when seen.
        f = make_functional("greet", functional_type="greeting")
        ctx = make_context(registry=make_registry(f), completed_ids=["greet"])
        assert FunctionalSlot(functional_type="greeting").resolve(ctx) is f

    def test_random_choice_among_multiple_candidates(self):
        f1 = make_functional("g1", functional_type="greeting")
        f2 = make_functional("g2", functional_type="greeting")
        reg = make_registry(f1, f2)
        random.seed(7)
        seen = set()
        for _ in range(30):
            ctx = make_context(registry=reg)
            seen.add(FunctionalSlot(functional_type="greeting").resolve(ctx).dialog_id)
        assert seen == {"g1", "g2"}

    def test_custom_policy_can_exclude_seen(self):
        f = make_functional("greet", functional_type="greeting")
        ctx = make_context(registry=make_registry(f), completed_ids=["greet"])
        block_seen = EligibilityPolicy([ExcludeIfSeenRule()])
        result = FunctionalSlot(
            functional_type="greeting", eligibility_policy=block_seen
        ).resolve(ctx)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# LLMDialogRef
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMDialogRefConstruction:
    def test_type_literal(self):
        assert LLMDialogRef(id="chat").type == "llm_dialog_ref"

    def test_id_stored(self):
        assert LLMDialogRef(id="chat").id == "chat"

    def test_overrides_default_none(self):
        ref = LLMDialogRef(id="chat")
        assert ref.max_turns is None
        assert ref.duration is None

    def test_overrides_stored(self):
        ref = LLMDialogRef(id="chat", max_turns=3, duration=90.0)
        assert ref.max_turns == 3
        assert ref.duration == 90.0

    def test_id_required(self):
        with pytest.raises(ValidationError):
            LLMDialogRef.model_validate({"type": "llm_dialog_ref"})


class TestLLMDialogRefResolve:
    def test_returns_dialog_when_found(self):
        llm = make_llm("chat")
        ctx = make_context(registry=make_registry(llm))
        assert LLMDialogRef(id="chat").resolve(ctx) is llm

    def test_returns_none_for_missing_id(self, caplog):
        ctx = make_context(registry=make_registry())
        with caplog.at_level(logging.WARNING):
            result = LLMDialogRef(id="ghost").resolve(ctx)
        assert result is None
        assert "ghost" in caplog.text

    def test_returns_none_for_wrong_type(self, caplog):
        n = make_narrative("n1")
        ctx = make_context(registry=make_registry(n))
        with caplog.at_level(logging.WARNING):
            result = LLMDialogRef(id="n1").resolve(ctx)
        assert result is None
        assert "not an LLMMiniDialog" in caplog.text

    def test_max_turns_override_produces_new_instance(self):
        llm = make_llm("chat", max_turns=10)
        ctx = make_context(registry=make_registry(llm))
        result = LLMDialogRef(id="chat", max_turns=3).resolve(ctx)
        assert result is not llm
        assert result.max_turns == 3
        assert llm.max_turns == 10  # original unchanged

    def test_duration_override_produces_new_instance(self):
        llm = make_llm("chat", duration=60.0)
        ctx = make_context(registry=make_registry(llm))
        result = LLMDialogRef(id="chat", duration=120.0).resolve(ctx)
        assert result is not llm
        assert result.duration == 120.0
        assert llm.duration == 60.0  # original unchanged

    def test_no_overrides_returns_same_instance(self):
        llm = make_llm("chat")
        ctx = make_context(registry=make_registry(llm))
        result = LLMDialogRef(id="chat").resolve(ctx)
        assert result is llm

    def test_registry_entry_not_mutated_after_override(self):
        llm = make_llm("chat", max_turns=5)
        reg = make_registry(llm)
        ctx = make_context(registry=reg)
        LLMDialogRef(id="chat", max_turns=1).resolve(ctx)
        # Registry must still hold the original
        assert reg.get_by_id("chat").max_turns == 5


# ─────────────────────────────────────────────────────────────────────────────
# AnyAgendaItem discriminated union
# ─────────────────────────────────────────────────────────────────────────────

class TestAnyAgendaItemUnion:
    @pytest.mark.parametrize("data,expected_type", [
        ({"type": "dialog_ref", "id": "x"}, "dialog_ref"),
        ({"type": "narrative_slot", "thread": "intro"}, "narrative_slot"),
        ({"type": "chitchat_slot"}, "chitchat_slot"),
        ({"type": "functional_slot", "functional_type": "greeting"}, "functional_slot"),
        ({"type": "llm_dialog_ref", "id": "chat"}, "llm_dialog_ref"),
    ])
    def test_all_types_parse_via_coerce(self, data, expected_type):
        item = to_agenda_item(data)
        assert item.type == expected_type

    def test_unknown_type_raises(self):
        with pytest.raises(Exception):
            to_agenda_item({"type": "unknown_slot"})

    def test_narrative_slot_bounds_survives_coerce(self):
        item = to_agenda_item(
            {"type": "narrative_slot", "thread": "main", "bounds": {"count_min": 2, "count_max": 5}}
        )
        assert item.bounds.count_min == 2
        assert item.bounds.count_max == 5

    def test_chitchat_slot_topics_filter_survives_coerce(self):
        item = to_agenda_item(
            {"type": "chitchat_slot", "topics_filter": ["food", "travel"]}
        )
        assert item.topics_filter == ["food", "travel"]

    def test_llm_dialog_ref_overrides_survive_coerce(self):
        item = to_agenda_item(
            {"type": "llm_dialog_ref", "id": "chat", "max_turns": 3, "duration": 60.0}
        )
        assert item.max_turns == 3
        assert item.duration == 60.0
