from types import SimpleNamespace

import pytest

from nardial import eligibility
from nardial.dialog_registry import DialogRegistry
from nardial.eligibility import (
    DependencyMetRule,
    EligibilityContext,
    EligibilityPolicy,
    EligibilityRule,
    EligibilityScope,
    ExcludeIfSeenRule,
    NarrativeOrderingRule,
    VariableDependencyMetRule,
    build_rule,
    get_rule,
    is_dialog_eligible,
    register_rule,
    rule_names,
)
from nardial.mini_dialogs import FunctionalDialog, NarrativeDialog


def make_dialog(dialog_id, dependencies=None, variable_dependencies=None):
    return SimpleNamespace(
        dialog_id=dialog_id,
        dependencies=dependencies or [],
        variable_dependencies=variable_dependencies or [],
    )


def make_narrative(dialog_id, thread, position):
    return NarrativeDialog(dialog_id=dialog_id, moves=[], thread=thread, position=position)


def make_functional(dialog_id, functional_type):
    return FunctionalDialog(dialog_id=dialog_id, moves=[], type=functional_type)


def test_exclude_if_seen_rule_participant_scope():
    rule = ExcludeIfSeenRule()
    dialog = make_dialog("greeting")

    assert rule.is_eligible(dialog, EligibilityContext(completed_ids=["greeting"])) is False
    assert rule.is_eligible(dialog, EligibilityContext(completed_ids=["other"])) is True


def test_exclude_if_seen_rule_session_scope_ignores_participant_history():
    rule = ExcludeIfSeenRule(scope=EligibilityScope.SESSION)
    dialog = make_dialog("chitchat_1")

    completed_in_past_session = EligibilityContext(completed_ids=["chitchat_1"], session_completed_ids=[])
    assert rule.is_eligible(dialog, completed_in_past_session) is True

    completed_this_session = EligibilityContext(completed_ids=[], session_completed_ids=["chitchat_1"])
    assert rule.is_eligible(dialog, completed_this_session) is False


def test_dependency_met_rule():
    rule = DependencyMetRule()
    dialog = make_dialog("farewell", dependencies=["greeting"])

    assert rule.is_eligible(dialog, EligibilityContext(completed_ids=[])) is False
    assert rule.is_eligible(dialog, EligibilityContext(completed_ids=["greeting"])) is True


def test_variable_dependency_met_rule_required_vs_optional():
    rule = VariableDependencyMetRule()
    dialog = make_dialog(
        "pet_chat",
        variable_dependencies=[
            {"variable": "has_pet", "required": True},
            {"variable": "pet_name", "required": False},
        ],
    )

    assert rule.is_eligible(dialog, EligibilityContext(user_model={})) is False
    assert rule.is_eligible(dialog, EligibilityContext(user_model={"has_pet": True})) is True


def test_variable_dependency_met_rule_defaults_to_eligible_without_attribute():
    rule = VariableDependencyMetRule()
    dialog = SimpleNamespace(dialog_id="no_var_deps")

    assert rule.is_eligible(dialog, EligibilityContext()) is True


def test_narrative_ordering_rule_blocks_until_earlier_positions_complete():
    step1 = make_narrative("thread_a_step_1", thread="thread_a", position=1)
    step2 = make_narrative("thread_a_step_2", thread="thread_a", position=2)
    registry = DialogRegistry.build([step1, step2])
    rule = NarrativeOrderingRule()

    not_started = EligibilityContext(registry=registry, completed_ids=[])
    assert rule.is_eligible(step2, not_started) is False
    assert rule.is_eligible(step1, not_started) is True

    step1_done = EligibilityContext(registry=registry, completed_ids=["thread_a_step_1"])
    assert rule.is_eligible(step2, step1_done) is True


def test_narrative_ordering_rule_ignores_dialogs_without_thread_or_position():
    rule = NarrativeOrderingRule()
    dialog = make_dialog("chitchat_1")

    assert rule.is_eligible(dialog, EligibilityContext(registry=DialogRegistry.build([]))) is True


def test_narrative_ordering_rule_defaults_to_eligible_without_registry():
    step2 = make_narrative("thread_a_step_2", thread="thread_a", position=2)
    rule = NarrativeOrderingRule()

    assert rule.is_eligible(step2, EligibilityContext(registry=None, completed_ids=[])) is True


def test_eligibility_policy_requires_every_rule_to_pass():
    dialog = make_dialog("greeting", dependencies=["intro"])
    policy = EligibilityPolicy([ExcludeIfSeenRule(), DependencyMetRule()])

    assert policy.is_eligible(dialog, EligibilityContext(completed_ids=[])) is False
    assert policy.is_eligible(dialog, EligibilityContext(completed_ids=["intro", "greeting"])) is False
    assert policy.is_eligible(dialog, EligibilityContext(completed_ids=["intro"])) is True


def test_is_dialog_eligible_default_policy_excludes_completed_narrative_dialog():
    dialog = make_narrative("step_1", thread="thread_a", position=1)

    assert is_dialog_eligible(dialog, EligibilityContext(completed_ids=[])) is True
    assert is_dialog_eligible(dialog, EligibilityContext(completed_ids=["step_1"])) is False


def test_is_dialog_eligible_explicit_policy_overrides_default():
    dialog = make_narrative("step_1", thread="thread_a", position=1)
    # No ExcludeIfSeenRule here: completion should no longer exclude it.
    permissive_policy = EligibilityPolicy([DependencyMetRule()])

    assert is_dialog_eligible(
        dialog, EligibilityContext(completed_ids=["step_1"]), policy=permissive_policy
    ) is True


def test_is_dialog_eligible_functional_dialog_reruns_after_completion():
    greeting = make_functional("greeting_1", functional_type="greeting")

    assert is_dialog_eligible(greeting, EligibilityContext(completed_ids=["greeting_1"])) is True


def test_is_dialog_eligible_enforces_narrative_ordering_via_registry():
    step1 = make_narrative("step_1", thread="thread_a", position=1)
    step2 = make_narrative("step_2", thread="thread_a", position=2)
    registry = DialogRegistry.build([step1, step2])

    assert is_dialog_eligible(step2, EligibilityContext(registry=registry, completed_ids=[])) is False
    assert is_dialog_eligible(step2, EligibilityContext(registry=registry, completed_ids=["step_1"])) is True


# --- rule registry / JSON rule specs ---

@pytest.fixture
def isolated_rules(monkeypatch):
    # Custom rules registered in a test must not leak into other tests.
    monkeypatch.setattr(eligibility, "_RULES", dict(eligibility._RULES))


def test_builtin_rules_are_registered_by_name():
    assert get_rule("exclude_if_seen") is ExcludeIfSeenRule
    assert get_rule("dependency_met") is DependencyMetRule
    assert get_rule("variable_dependency_met") is VariableDependencyMetRule
    assert get_rule("narrative_ordering") is NarrativeOrderingRule
    assert rule_names()[:4] == ["exclude_if_seen", "dependency_met", "variable_dependency_met", "narrative_ordering"]


def test_build_rule_from_bare_name():
    rule = build_rule("dependency_met")
    assert isinstance(rule, DependencyMetRule)


def test_build_rule_converts_exclude_if_seen_scope():
    rule = build_rule({"rule": "exclude_if_seen", "scope": "session"})
    assert rule.scope == EligibilityScope.SESSION
    assert build_rule("exclude_if_seen").scope == EligibilityScope.PARTICIPANT


@pytest.mark.parametrize("rule", [
    ExcludeIfSeenRule(),
    ExcludeIfSeenRule(scope=EligibilityScope.SESSION),
    DependencyMetRule(),
    VariableDependencyMetRule(),
    NarrativeOrderingRule(),
])
def test_builtin_rules_roundtrip_through_dict(rule):
    rebuilt = build_rule(rule.to_dict())
    assert type(rebuilt) is type(rule)
    assert rebuilt.to_dict() == rule.to_dict()


@pytest.mark.parametrize("spec, message", [
    ("nope", "unknown eligibility rule 'nope'"),
    ({"rule": "exclude_if_seen", "scope": "forever"}, "invalid params for eligibility rule 'exclude_if_seen'"),
    ({"rule": "dependency_met", "extra": 1}, "invalid params for eligibility rule 'dependency_met'"),
    ({"scope": "session"}, "rule spec must be"),
    (42, "rule spec must be"),
])
def test_build_rule_rejects_bad_specs(spec, message):
    with pytest.raises(ValueError, match=message):
        build_rule(spec)


def test_custom_rule_registers_and_builds_with_params(isolated_rules):
    @register_rule("user_model_contains")
    class UserModelContains(EligibilityRule):
        def __init__(self, variable, item):
            self.variable = variable
            self.item = item

        def is_eligible(self, dialog, context):
            return self.item in (context.user_model.get(self.variable) or [])

        def to_dict(self):
            return {**super().to_dict(), "variable": self.variable, "item": self.item}

    spec = {"rule": "user_model_contains", "variable": "hobbies", "item": "music"}
    rule = build_rule(spec)
    dialog = make_dialog("d1")

    assert rule.to_dict() == spec
    assert rule.is_eligible(dialog, EligibilityContext(user_model={"hobbies": ["music", "chess"]}))
    assert not rule.is_eligible(dialog, EligibilityContext(user_model={"hobbies": ["chess"]}))
    assert not rule.is_eligible(dialog, EligibilityContext())


def test_registering_taken_rule_name_to_other_class_raises(isolated_rules):
    with pytest.raises(ValueError, match="already registered"):
        @register_rule("dependency_met")
        class Impostor(EligibilityRule):
            def is_eligible(self, dialog, context):
                return True

    assert get_rule("dependency_met") is DependencyMetRule
