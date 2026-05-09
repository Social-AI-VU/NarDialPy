"""Tests for EligibilityPolicy and all EligibilityRule subclasses."""

import pytest

from nardial.agenda.items import AgendaContext
from nardial.eligibility import (
    DepsMetRule,
    EligibilityPolicy,
    EligibilityRule,
    ExcludeIfSeenRule,
    NarrativeOrderingRule,
    VariableDepsMetRule,
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

def make_registry(*dialogs):
    return DialogRegistry.build(list(dialogs))


def make_context(registry=None, completed_ids=None, session_completed_ids=None, user_model=None):
    return AgendaContext(
        registry=registry or make_registry(),
        completed_ids=set(completed_ids or []),
        session_completed_ids=set(session_completed_ids or []),
        user_model=user_model or {},
    )


def make_narrative(dialog_id, thread="main", position=1, dependencies=None):
    return NarrativeDialog(
        dialog_id=dialog_id, moves=[], thread=thread, position=position,
        dependencies=dependencies or [],
    )


def make_chitchat(dialog_id, topics=None, dependencies=None, variable_dependencies=None):
    return ChitchatDialog(
        dialog_id=dialog_id, moves=[], topics=topics or [],
        dependencies=dependencies or [],
        variable_dependencies=variable_dependencies or [],
    )


def make_functional(dialog_id, functional_type="greeting"):
    return FunctionalDialog(dialog_id=dialog_id, moves=[], type=functional_type)


def make_llm(dialog_id):
    return LLMDialog(dialog_id=dialog_id, prompt="Chat.")


# ── EligibilityRule is abstract ───────────────────────────────────────────────

class TestEligibilityRuleIsAbstract:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            EligibilityRule()  # type: ignore[abstract]


# ── ExcludeIfSeenRule ─────────────────────────────────────────────────────────

class TestExcludeIfSeenRule:
    def test_unseen_dialog_is_eligible(self):
        rule = ExcludeIfSeenRule()
        ctx = make_context(completed_ids=[])
        assert rule.is_eligible(make_narrative("n1"), ctx)

    def test_seen_dialog_blocked_participant_scope(self):
        rule = ExcludeIfSeenRule(scope="participant")
        ctx = make_context(completed_ids=["n1"])
        assert not rule.is_eligible(make_narrative("n1"), ctx)

    def test_participant_scope_does_not_check_session_completed(self):
        # Only checks completed_ids, not session_completed_ids.
        rule = ExcludeIfSeenRule(scope="participant")
        ctx = make_context(completed_ids=[], session_completed_ids=["n1"])
        assert rule.is_eligible(make_narrative("n1"), ctx)

    def test_session_scope_blocked_by_session_completed(self):
        rule = ExcludeIfSeenRule(scope="session")
        ctx = make_context(completed_ids=[], session_completed_ids=["n1"])
        assert not rule.is_eligible(make_narrative("n1"), ctx)

    def test_session_scope_allows_cross_session_history(self):
        # A dialog completed in a prior session passes with scope="session".
        rule = ExcludeIfSeenRule(scope="session")
        ctx = make_context(completed_ids=["n1"], session_completed_ids=[])
        assert rule.is_eligible(make_narrative("n1"), ctx)

    def test_default_scope_is_participant(self):
        rule = ExcludeIfSeenRule()
        assert rule.scope == "participant"


# ── DepsMetRule ───────────────────────────────────────────────────────────────

class TestDepsMetRule:
    def test_no_deps_always_passes(self):
        rule = DepsMetRule()
        ctx = make_context(completed_ids=[])
        assert rule.is_eligible(make_narrative("n1"), ctx)

    def test_satisfied_dep_passes(self):
        rule = DepsMetRule()
        n = make_narrative("n2", dependencies=["n1"])
        ctx = make_context(completed_ids=["n1"])
        assert rule.is_eligible(n, ctx)

    def test_unsatisfied_dep_blocked(self):
        rule = DepsMetRule()
        n = make_narrative("n2", dependencies=["n1"])
        ctx = make_context(completed_ids=[])
        assert not rule.is_eligible(n, ctx)

    def test_all_deps_must_be_satisfied(self):
        rule = DepsMetRule()
        n = make_narrative("n3", dependencies=["n1", "n2"])
        assert not rule.is_eligible(n, make_context(completed_ids=["n1"]))
        assert rule.is_eligible(n, make_context(completed_ids=["n1", "n2"]))


# ── VariableDepsMetRule ───────────────────────────────────────────────────────

class TestVariableDepsMetRule:
    def test_no_var_deps_always_passes(self):
        rule = VariableDepsMetRule()
        assert rule.is_eligible(make_chitchat("c1"), make_context())

    def test_required_var_present_passes(self):
        rule = VariableDepsMetRule()
        c = make_chitchat("c1", variable_dependencies=[{"variable": "name", "required": True}])
        ctx = make_context(user_model={"name": "Alice"})
        assert rule.is_eligible(c, ctx)

    def test_required_var_missing_blocked(self):
        rule = VariableDepsMetRule()
        c = make_chitchat("c1", variable_dependencies=[{"variable": "name", "required": True}])
        assert not rule.is_eligible(c, make_context(user_model={}))

    def test_optional_var_missing_passes(self):
        rule = VariableDepsMetRule()
        c = make_chitchat("c1", variable_dependencies=[{"variable": "name", "required": False}])
        assert rule.is_eligible(c, make_context(user_model={}))

    def test_uses_real_user_model_not_empty_dict(self):
        # This is the bug that was fixed: old code used user_model={} hardcoded.
        rule = VariableDepsMetRule()
        c = make_chitchat("c1", variable_dependencies=[{"variable": "age", "required": True}])
        assert not rule.is_eligible(c, make_context(user_model={}))
        assert rule.is_eligible(c, make_context(user_model={"age": "25"}))


# ── NarrativeOrderingRule ─────────────────────────────────────────────────────

class TestNarrativeOrderingRule:
    def test_non_narrative_always_passes(self):
        rule = NarrativeOrderingRule()
        ctx = make_context(registry=make_registry())
        assert rule.is_eligible(make_chitchat("c1"), ctx)

    def test_first_position_passes_when_no_siblings(self):
        rule = NarrativeOrderingRule()
        n1 = make_narrative("n1", thread="main", position=1)
        ctx = make_context(registry=make_registry(n1))
        assert rule.is_eligible(n1, ctx)

    def test_second_position_blocked_when_first_incomplete(self):
        rule = NarrativeOrderingRule()
        n1 = make_narrative("n1", thread="main", position=1)
        n2 = make_narrative("n2", thread="main", position=2)
        reg = make_registry(n1, n2)
        ctx = make_context(registry=reg, completed_ids=[])
        assert not rule.is_eligible(n2, ctx)

    def test_second_position_passes_when_first_complete(self):
        rule = NarrativeOrderingRule()
        n1 = make_narrative("n1", thread="main", position=1)
        n2 = make_narrative("n2", thread="main", position=2)
        reg = make_registry(n1, n2)
        ctx = make_context(registry=reg, completed_ids=["n1"])
        assert rule.is_eligible(n2, ctx)

    def test_different_threads_do_not_block_each_other(self):
        rule = NarrativeOrderingRule()
        a1 = make_narrative("a1", thread="thread_a", position=1)
        b2 = make_narrative("b2", thread="thread_b", position=2)
        reg = make_registry(a1, b2)
        ctx = make_context(registry=reg, completed_ids=[])
        # b2 at position 2 in thread_b is only blocked by thread_b siblings
        assert rule.is_eligible(b2, ctx)

    def test_uses_registry_not_linear_scan(self):
        # Registry lookup means only same-thread siblings are considered,
        # regardless of how many other dialogs exist.
        rule = NarrativeOrderingRule()
        n1 = make_narrative("n1", thread="main", position=1)
        n2 = make_narrative("n2", thread="main", position=2)
        extra = make_chitchat("c_extra")
        reg = make_registry(n1, n2, extra)
        ctx = make_context(registry=reg, completed_ids=[])
        assert not rule.is_eligible(n2, ctx)


# ── EligibilityPolicy ─────────────────────────────────────────────────────────

class TestEligibilityPolicy:
    def test_empty_policy_always_passes(self):
        policy = EligibilityPolicy([])
        assert policy.is_eligible(make_narrative("n1"), make_context())

    def test_all_rules_must_pass(self):
        ctx = make_context(completed_ids=["n1"])
        policy = EligibilityPolicy([ExcludeIfSeenRule(), DepsMetRule()])
        assert not policy.is_eligible(make_narrative("n1"), ctx)

    def test_short_circuits_on_first_failing_rule(self):
        # ExcludeIfSeenRule fails first — DepsMetRule is never reached.
        ctx = make_context(completed_ids=["n1"])
        rule_a = ExcludeIfSeenRule()
        rule_b = DepsMetRule()
        policy = EligibilityPolicy([rule_a, rule_b])
        assert not policy.is_eligible(make_narrative("n1"), ctx)

    def test_repr_lists_rule_names(self):
        policy = EligibilityPolicy([ExcludeIfSeenRule(), DepsMetRule()])
        r = repr(policy)
        assert "ExcludeIfSeenRule" in r
        assert "DepsMetRule" in r


# ── DEFAULT_ELIGIBILITY on dialog classes ─────────────────────────────────────

class TestDefaultEligibilityAttachment:
    def test_narrative_default_eligibility_is_set(self):
        assert NarrativeDialog.DEFAULT_ELIGIBILITY is not None
        assert isinstance(NarrativeDialog.DEFAULT_ELIGIBILITY, EligibilityPolicy)

    def test_chitchat_default_eligibility_is_set(self):
        assert ChitchatDialog.DEFAULT_ELIGIBILITY is not None

    def test_functional_default_eligibility_is_set(self):
        assert FunctionalDialog.DEFAULT_ELIGIBILITY is not None

    def test_llm_default_eligibility_is_set(self):
        assert LLMDialog.DEFAULT_ELIGIBILITY is not None

    def test_functional_has_no_exclude_if_seen_rule(self):
        # FunctionalDialog (greetings) must re-run every session.
        policy = FunctionalDialog.DEFAULT_ELIGIBILITY
        rule_types = [type(r) for r in policy.rules]
        assert ExcludeIfSeenRule not in rule_types

    def test_narrative_has_all_four_rules(self):
        policy = NarrativeDialog.DEFAULT_ELIGIBILITY
        rule_types = {type(r) for r in policy.rules}
        assert rule_types == {ExcludeIfSeenRule, DepsMetRule, VariableDepsMetRule, NarrativeOrderingRule}


# ── is_dialog_eligible integration ───────────────────────────────────────────

class TestIsDialogEligibleWithPolicy:
    """Verify that DialogLogic.is_dialog_eligible uses and respects policies."""

    def test_custom_policy_overrides_class_default(self):
        from nardial.dialog_logic import DialogLogic
        # FunctionalDialog default has no ExcludeIfSeenRule, but a custom policy does.
        f = make_functional("greeting")
        custom = EligibilityPolicy([ExcludeIfSeenRule()])
        result = DialogLogic.is_dialog_eligible(f, completed_ids=["greeting"], user_model={}, policy=custom)
        assert not result

    def test_functional_passes_when_completed_under_default_policy(self):
        from nardial.dialog_logic import DialogLogic
        f = make_functional("greeting")
        # Default policy has no ExcludeIfSeenRule → should pass even when completed.
        assert DialogLogic.is_dialog_eligible(f, completed_ids=["greeting"], user_model={})

    def test_narrative_blocked_when_completed_under_default_policy(self):
        from nardial.dialog_logic import DialogLogic
        n = make_narrative("n1")
        assert not DialogLogic.is_dialog_eligible(n, completed_ids=["n1"], user_model={})
