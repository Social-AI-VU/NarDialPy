from types import SimpleNamespace

from nardial.dialog_registry import DialogRegistry
from nardial.eligibility import (
    DependencyMetRule,
    EligibilityContext,
    EligibilityPolicy,
    EligibilityScope,
    ExcludeIfSeenRule,
    NarrativeOrderingRule,
    VariableDependencyMetRule,
    is_dialog_eligible,
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
