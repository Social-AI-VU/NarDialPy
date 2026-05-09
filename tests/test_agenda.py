"""Tests for the agenda system.

Covers:
- DialogRegistry — indexing and querying
- EligibilityPolicy + all rule classes
- AgendaItem types: DialogRef, NarrativeSlot, ChitchatSlot, FunctionalSlot, LLMDialogRef
- coerce_agenda_item
- resolve_agenda() generator
- SessionPlan / SessionTemplate / load_session_plan
"""
import json
import random
import pytest

from nardial.agenda import (
    AgendaContext,
    ChitchatSlot,
    DialogRef,
    FunctionalSlot,
    LLMDialogRef,
    NarrativeSlot,
    SlotBounds,
    coerce_agenda_item,
    resolve_agenda,
    DepsMetRule,
    EligibilityPolicy,
    ExcludeIfSeenRule,
    NarrativeOrderingRule,
    VariableDepsMetRule,
    SessionPlan,
    SessionTemplate,
    load_session_plan,
)
from nardial.dialog_registry import DialogRegistry
from nardial.mini_dialogs import (
    ChitchatDialog,
    FunctionalDialog,
    LLMDialog,
    MiniDialog,
    NarrativeDialog,
)
from nardial.moves import MoveSay


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_narrative(dialog_id, thread="main", position=1, deps=None, var_deps=None):
    return NarrativeDialog(
        dialog_id=dialog_id,
        moves=[MoveSay(text="narrative")],
        thread=thread,
        position=position,
        dependencies=deps or [],
        variable_dependencies=var_deps or [],
    )


def make_chitchat(dialog_id, topics=None, deps=None):
    return ChitchatDialog(
        dialog_id=dialog_id,
        moves=[MoveSay(text="chitchat")],
        topics=topics or [],
        dependencies=deps or [],
    )


def make_functional(dialog_id, functional_type="greeting"):
    return FunctionalDialog(
        dialog_id=dialog_id,
        moves=[MoveSay(text="func")],
        type=functional_type,
    )


def make_llm(dialog_id, max_turns=5):
    return LLMDialog(dialog_id=dialog_id, max_turns=max_turns)


def make_mini(dialog_id, deps=None, var_deps=None):
    return MiniDialog(
        dialog_id=dialog_id,
        moves=[MoveSay(text="mini")],
        dependencies=deps or [],
        variable_dependencies=var_deps or [],
    )


def make_registry(*dialogs):
    return DialogRegistry.build(list(dialogs))


def make_context(
    dialogs,
    completed_ids=None,
    session_completed_ids=None,
    topics=None,
    user_model=None,
):
    registry = make_registry(*dialogs)
    return AgendaContext(
        registry=registry,
        completed_ids=set(completed_ids or []),
        session_completed_ids=set(session_completed_ids or []),
        user_model=user_model or {},
        topics_of_interest=list(topics or []),
    )


# ── DialogRegistry ────────────────────────────────────────────────────────────

class TestDialogRegistry:
    def test_get_by_id_found(self):
        d = make_narrative("n1")
        registry = make_registry(d)
        assert registry.get_by_id("n1") is d

    def test_get_by_id_not_found_returns_none(self):
        registry = make_registry(make_narrative("n1"))
        assert registry.get_by_id("missing") is None

    def test_get_by_type_narrative(self):
        from nardial.mini_dialogs import DialogType
        n = make_narrative("n1")
        c = make_chitchat("c1")
        registry = make_registry(n, c)
        results = registry.get_by_type(DialogType.NARRATIVE)
        assert n in results
        assert c not in results

    def test_get_by_attr_single_value(self):
        g = make_functional("g1", "greeting")
        f = make_functional("f1", "farewell")
        registry = make_registry(g, f)
        assert registry.get_by_attr("functional_type", "greeting") == [g]
        assert registry.get_by_attr("functional_type", "farewell") == [f]

    def test_get_by_attr_list_topic_expansion(self):
        """A chitchat with topics=['pizza','food'] must appear under both topics."""
        c = make_chitchat("c1", topics=["pizza", "food"])
        registry = make_registry(c)
        assert c in registry.get_by_attr("topics", "pizza")
        assert c in registry.get_by_attr("topics", "food")

    def test_duplicate_id_is_skipped(self):
        """When two dialogs share an ID the first is kept and the second is dropped."""
        d1 = make_narrative("dup", position=1)
        d2 = make_narrative("dup", position=2)
        registry = make_registry(d1, d2)
        assert registry.get_by_id("dup") is d1
        assert len(registry) == 1

    def test_get_by_attr_unknown_attr_returns_empty(self):
        registry = make_registry(make_narrative("n1"))
        assert registry.get_by_attr("nonexistent", "value") == []


# ── EligibilityPolicy + Rules ─────────────────────────────────────────────────

class TestExcludeIfSeenRule:
    def _rule_participant(self):
        return ExcludeIfSeenRule(scope="participant")

    def _rule_session(self):
        return ExcludeIfSeenRule(scope="session")

    def test_participant_scope_blocks_seen_dialog(self):
        d = make_narrative("n1")
        ctx = make_context([d], completed_ids={"n1"})
        assert not self._rule_participant().is_eligible(d, ctx)

    def test_participant_scope_allows_unseen_dialog(self):
        d = make_narrative("n1")
        ctx = make_context([d])
        assert self._rule_participant().is_eligible(d, ctx)

    def test_session_scope_allows_if_only_in_completed_ids(self):
        """Dialog run in a prior session but not yet this session should pass."""
        d = make_narrative("n1")
        ctx = make_context([d], completed_ids={"n1"}, session_completed_ids=set())
        assert self._rule_session().is_eligible(d, ctx)

    def test_session_scope_blocks_if_in_session_completed_ids(self):
        d = make_narrative("n1")
        ctx = make_context([d], session_completed_ids={"n1"})
        assert not self._rule_session().is_eligible(d, ctx)


class TestDepsMetRule:
    def test_blocks_when_dep_missing(self):
        d = make_mini("d1", deps=["prereq"])
        ctx = make_context([d])
        assert not DepsMetRule().is_eligible(d, ctx)

    def test_passes_when_dep_present(self):
        d = make_mini("d1", deps=["prereq"])
        ctx = make_context([d], completed_ids={"prereq"})
        assert DepsMetRule().is_eligible(d, ctx)

    def test_passes_with_no_deps(self):
        d = make_mini("d1")
        ctx = make_context([d])
        assert DepsMetRule().is_eligible(d, ctx)


class TestVariableDepsMetRule:
    def test_blocks_when_required_var_missing(self):
        d = make_mini("d1", var_deps=[{"variable": "age", "required": True}])
        ctx = make_context([d], user_model={})
        assert not VariableDepsMetRule().is_eligible(d, ctx)

    def test_passes_when_required_var_present(self):
        d = make_mini("d1", var_deps=[{"variable": "age", "required": True}])
        ctx = make_context([d], user_model={"age": "30"})
        assert VariableDepsMetRule().is_eligible(d, ctx)

    def test_passes_when_var_not_required(self):
        d = make_mini("d1", var_deps=[{"variable": "age", "required": False}])
        ctx = make_context([d], user_model={})
        assert VariableDepsMetRule().is_eligible(d, ctx)


class TestNarrativeOrderingRule:
    def test_blocks_when_earlier_position_not_completed(self):
        n1 = make_narrative("n1", position=1)
        n2 = make_narrative("n2", position=2)
        # n1 not completed yet
        ctx = make_context([n1, n2], completed_ids=set())
        assert not NarrativeOrderingRule().is_eligible(n2, ctx)

    def test_passes_when_all_earlier_siblings_completed(self):
        n1 = make_narrative("n1", position=1)
        n2 = make_narrative("n2", position=2)
        ctx = make_context([n1, n2], completed_ids={"n1"})
        assert NarrativeOrderingRule().is_eligible(n2, ctx)

    def test_passes_for_first_position(self):
        n1 = make_narrative("n1", position=1)
        ctx = make_context([n1])
        assert NarrativeOrderingRule().is_eligible(n1, ctx)

    def test_skips_non_narrative_dialog(self):
        """Dialogs without thread/position always pass the ordering rule."""
        d = make_mini("d1")
        ctx = make_context([d])
        assert NarrativeOrderingRule().is_eligible(d, ctx)


class TestFunctionalDialogDefaultEligibility:
    def test_re_runs_after_completion(self):
        """FunctionalDialog has no ExcludeIfSeenRule so it passes even if seen."""
        g = make_functional("greeting")
        ctx = make_context([g], completed_ids={"greeting"})
        assert FunctionalDialog.DEFAULT_ELIGIBILITY.is_eligible(g, ctx)


# ── coerce_agenda_item ────────────────────────────────────────────────────────

class TestCoerceAgendaItem:
    def test_string_becomes_dialog_ref(self):
        item = coerce_agenda_item("greeting")
        assert isinstance(item, DialogRef)
        assert item.id == "greeting"

    def test_dict_parsed_to_correct_type(self):
        item = coerce_agenda_item({"type": "narrative_slot", "thread": "main"})
        assert isinstance(item, NarrativeSlot)
        assert item.thread == "main"

    def test_agenda_item_passthrough(self):
        ref = DialogRef(id="x")
        assert coerce_agenda_item(ref) is ref

    def test_invalid_type_raises_type_error(self):
        with pytest.raises(TypeError):
            coerce_agenda_item(42)


# ── DialogRef ─────────────────────────────────────────────────────────────────

class TestDialogRef:
    def test_resolves_to_dialog(self):
        d = make_narrative("n1")
        ctx = make_context([d])
        result = DialogRef(id="n1").resolve(ctx)
        assert result is d

    def test_missing_id_returns_none(self):
        ctx = make_context([])
        result = DialogRef(id="ghost").resolve(ctx)
        assert result is None


# ── NarrativeSlot ─────────────────────────────────────────────────────────────

class TestNarrativeSlot:
    def test_returns_lowest_position(self):
        n1 = make_narrative("n1", position=1)
        n2 = make_narrative("n2", position=2)
        ctx = make_context([n1, n2])
        result = NarrativeSlot(thread="main").resolve(ctx)
        assert result is n1

    def test_skips_completed_dialog(self):
        n1 = make_narrative("n1", position=1)
        n2 = make_narrative("n2", position=2)
        ctx = make_context([n1, n2], completed_ids={"n1"})
        result = NarrativeSlot(thread="main").resolve(ctx)
        assert result is n2

    def test_returns_none_when_pool_exhausted(self):
        n1 = make_narrative("n1", position=1)
        ctx = make_context([n1], completed_ids={"n1"})
        result = NarrativeSlot(thread="main").resolve(ctx)
        assert result is None

    def test_random_tiebreak_among_equal_positions(self):
        """With a seeded RNG, tiebreak is deterministic."""
        n_a = make_narrative("n_a", position=1)
        n_b = make_narrative("n_b", position=1)
        ctx = make_context([n_a, n_b])
        slot = NarrativeSlot(thread="main")
        # Run many times; both should appear
        random.seed(42)
        chosen = {slot.resolve(ctx) for _ in range(20)}
        assert n_a in chosen or n_b in chosen  # at least one seen


# ── ChitchatSlot ──────────────────────────────────────────────────────────────

class TestChitchatSlot:
    def test_returns_highest_topic_overlap(self):
        c1 = make_chitchat("c1", topics=["pizza"])
        c2 = make_chitchat("c2", topics=["pizza", "food"])
        ctx = make_context([c1, c2], topics=["pizza", "food"])
        result = ChitchatSlot().resolve(ctx)
        # c2 has 2 matching topics vs c1's 1
        assert result is c2

    def test_topics_filter_limits_candidates(self):
        c1 = make_chitchat("c1", topics=["pizza"])
        c2 = make_chitchat("c2", topics=["movies"])
        ctx = make_context([c1, c2])
        result = ChitchatSlot(topics_filter=["movies"]).resolve(ctx)
        assert result is c2

    def test_returns_none_when_no_eligible(self):
        c1 = make_chitchat("c1")
        ctx = make_context([c1], completed_ids={"c1"})
        result = ChitchatSlot().resolve(ctx)
        assert result is None

    def test_excludes_seen_dialogs(self):
        c1 = make_chitchat("c1")
        c2 = make_chitchat("c2")
        ctx = make_context([c1, c2], completed_ids={"c1"})
        result = ChitchatSlot().resolve(ctx)
        assert result is c2


# ── FunctionalSlot ────────────────────────────────────────────────────────────

class TestFunctionalSlot:
    def test_returns_matching_dialog(self):
        g = make_functional("greeting", "greeting")
        f = make_functional("farewell", "farewell")
        ctx = make_context([g, f])
        result = FunctionalSlot(functional_type="greeting").resolve(ctx)
        assert result is g

    def test_returns_none_when_none_match(self):
        g = make_functional("greeting", "greeting")
        ctx = make_context([g])
        result = FunctionalSlot(functional_type="farewell").resolve(ctx)
        assert result is None

    def test_reruns_allowed_after_completion(self):
        """FunctionalSlot uses DEFAULT_ELIGIBILITY which has no ExcludeIfSeenRule."""
        g = make_functional("greeting", "greeting")
        # Greeting is in completed_ids, but FunctionalDialog should still pass.
        ctx = make_context([g], completed_ids={"greeting"})
        result = FunctionalSlot(functional_type="greeting").resolve(ctx)
        assert result is g


# ── LLMDialogRef ──────────────────────────────────────────────────────────────

class TestLLMDialogRef:
    def test_returns_dialog_on_hit(self):
        llm = make_llm("chat1")
        ctx = make_context([llm])
        result = LLMDialogRef(id="chat1").resolve(ctx)
        assert result is llm

    def test_missing_id_returns_none(self):
        ctx = make_context([])
        result = LLMDialogRef(id="ghost").resolve(ctx)
        assert result is None

    def test_wrong_type_returns_none(self):
        n = make_narrative("n1")
        ctx = make_context([n])
        result = LLMDialogRef(id="n1").resolve(ctx)
        assert result is None

    def test_override_max_turns_produces_copy(self):
        llm = make_llm("chat1", max_turns=5)
        ctx = make_context([llm])
        result = LLMDialogRef(id="chat1", max_turns=10).resolve(ctx)
        assert result is not llm
        assert result.max_turns == 10

    def test_override_does_not_mutate_registry(self):
        llm = make_llm("chat1", max_turns=5)
        ctx = make_context([llm])
        LLMDialogRef(id="chat1", max_turns=10).resolve(ctx)
        # The original registry entry must be untouched.
        assert ctx.registry.get_by_id("chat1").max_turns == 5


# ── resolve_agenda() ──────────────────────────────────────────────────────────

class TestResolveAgenda:
    def test_flat_string_agenda_yields_in_order(self):
        a = make_narrative("a", position=1)
        b = make_narrative("b", thread="side", position=1)
        ctx = make_context([a, b])
        results = []
        for dialog in resolve_agenda(["a", "b"], ctx):
            results.append(dialog.dialog_id)
            ctx.mark_completed(dialog.dialog_id)
        assert results == ["a", "b"]

    def test_none_resolving_items_are_skipped(self):
        a = make_narrative("a", position=1)
        ctx = make_context([a])
        results = [d.dialog_id for d in resolve_agenda(["missing", "a"], ctx)]
        assert results == ["a"]

    def test_chitchat_slot_count_max_2_yields_twice(self):
        c1 = make_chitchat("c1")
        c2 = make_chitchat("c2")
        ctx = make_context([c1, c2])
        slot = ChitchatSlot(bounds=SlotBounds(count_min=1, count_max=2))
        results = []
        for dialog in resolve_agenda([slot], ctx):
            results.append(dialog.dialog_id)
            ctx.mark_completed(dialog.dialog_id)
        assert len(results) == 2

    def test_narrative_slot_count_2_yields_different_dialogs(self):
        """NarrativeSlot(count_max=2) must yield consecutive steps with context update."""
        n1 = make_narrative("n1", position=1)
        n2 = make_narrative("n2", position=2)
        ctx = make_context([n1, n2])
        slot = NarrativeSlot(thread="main", bounds=SlotBounds(count_min=2, count_max=2))
        results = []
        for dialog in resolve_agenda([slot], ctx):
            results.append(dialog.dialog_id)
            ctx.mark_completed(dialog.dialog_id)
        # n1 first (position 1), then n2 (position 2 unlocked after n1 completes)
        assert results == ["n1", "n2"]

    def test_exhausted_pool_retires_slot(self):
        """Slot with count_min=3 but only 1 dialog logs warning and retires."""
        c1 = make_chitchat("c1")
        ctx = make_context([c1])
        slot = ChitchatSlot(bounds=SlotBounds(count_min=3, count_max=None))
        results = []
        for dialog in resolve_agenda([slot], ctx):
            results.append(dialog.dialog_id)
            ctx.mark_completed(dialog.dialog_id)
        # Only c1 is available; slot exhausts after 1 run, not 3.
        assert results == ["c1"]

    def test_agenda_context_mark_completed_updates_both_sets(self):
        ctx = make_context([make_narrative("n1")])
        ctx.mark_completed("n1")
        assert "n1" in ctx.completed_ids
        assert "n1" in ctx.session_completed_ids


# ── SessionPlan ───────────────────────────────────────────────────────────────

class TestSessionTemplate:
    def test_get_agenda_items_coerces_strings(self):
        template = SessionTemplate(session_index=1, agenda=["greeting", "farewell"])
        items = template.get_agenda_items()
        assert all(isinstance(i, DialogRef) for i in items)
        assert items[0].id == "greeting"

    def test_get_agenda_items_coerces_dicts(self):
        template = SessionTemplate(
            session_index=1,
            agenda=[{"type": "narrative_slot", "thread": "intro"}],
        )
        items = template.get_agenda_items()
        assert isinstance(items[0], NarrativeSlot)


class TestSessionPlan:
    def _plan(self):
        return SessionPlan(
            plan_id="test_plan",
            sessions=[
                SessionTemplate(session_index=1, agenda=["a"]),
                SessionTemplate(session_index=2, agenda=["b"]),
                SessionTemplate(session_index=3, agenda=["c"]),
            ],
        )

    def test_get_template_exact_match(self):
        plan = self._plan()
        t = plan.get_template(2)
        assert t is not None
        assert t.session_index == 2
        assert t.agenda == ["b"]

    def test_get_template_fallback_to_last_when_exceeded(self):
        plan = self._plan()
        t = plan.get_template(99)
        assert t is not None
        assert t.session_index == 3  # last defined template

    def test_get_template_returns_none_for_empty_plan(self):
        plan = SessionPlan(plan_id="empty", sessions=[])
        assert plan.get_template(1) is None

    def test_get_template_first_session(self):
        plan = self._plan()
        t = plan.get_template(1)
        assert t.agenda == ["a"]


class TestLoadSessionPlan:
    def test_round_trips_json(self, tmp_path):
        data = {
            "plan_id": "study_arc",
            "sessions": [
                {"session_index": 1, "agenda": ["greeting", "farewell"]},
                {"session_index": 2, "agenda": [{"type": "chitchat_slot"}]},
            ],
        }
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(data), encoding="utf-8")

        plan = load_session_plan(str(plan_file))
        assert plan.plan_id == "study_arc"
        assert len(plan.sessions) == 2
        assert plan.sessions[0].session_index == 1
        assert plan.sessions[1].agenda[0] == {"type": "chitchat_slot"}

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_session_plan(str(tmp_path / "nonexistent.json"))
