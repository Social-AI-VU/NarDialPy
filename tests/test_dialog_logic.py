from nardial.dialog_logic import DialogLogic
from nardial.eligibility import DependencyMetRule, EligibilityPolicy
from nardial.mini_dialogs import ChitchatDialog, FunctionalDialog, NarrativeDialog


def make_narrative(dialog_id, thread, position, dependencies=None, variable_dependencies=None):
    return NarrativeDialog(
        dialog_id=dialog_id,
        moves=[],
        thread=thread,
        position=position,
        dependencies=dependencies,
        variable_dependencies=variable_dependencies,
    )


def make_functional(dialog_id, functional_type):
    return FunctionalDialog(dialog_id=dialog_id, moves=[], type=functional_type)


def make_chitchat(dialog_id, topics=None, dependencies=None, variable_dependencies=None):
    return ChitchatDialog(
        dialog_id=dialog_id,
        moves=[],
        theme="",
        topics=topics,
        dependencies=dependencies,
        variable_dependencies=variable_dependencies,
    )


def test_is_dialog_eligible_default_policy_excludes_completed_narrative_dialog():
    dialog = make_narrative("step_1", thread="thread_a", position=1)

    assert DialogLogic.is_dialog_eligible(dialog, completed_ids=[], user_model={}) is True
    assert DialogLogic.is_dialog_eligible(dialog, completed_ids=["step_1"], user_model={}) is False


def test_is_dialog_eligible_explicit_policy_overrides_default():
    dialog = make_narrative("step_1", thread="thread_a", position=1)
    # No ExcludeIfSeenRule here: completion should no longer exclude it.
    permissive_policy = EligibilityPolicy([DependencyMetRule()])

    assert DialogLogic.is_dialog_eligible(
        dialog, completed_ids=["step_1"], user_model={}, policy=permissive_policy
    ) is True


def test_is_dialog_eligible_functional_dialog_reruns_after_completion():
    greeting = make_functional("greeting_1", functional_type="greeting")

    assert DialogLogic.is_dialog_eligible(greeting, completed_ids=["greeting_1"], user_model={}) is True


def test_is_dialog_eligible_enforces_narrative_ordering_via_all_dialogs():
    step1 = make_narrative("step_1", thread="thread_a", position=1)
    step2 = make_narrative("step_2", thread="thread_a", position=2)

    assert DialogLogic.is_dialog_eligible(
        step2, completed_ids=[], user_model={}, all_dialogs=[step1, step2]
    ) is False
    assert DialogLogic.is_dialog_eligible(
        step2, completed_ids=["step_1"], user_model={}, all_dialogs=[step1, step2]
    ) is True


def test_insert_chitchat_into_session_respects_real_user_model():
    chitchat = make_chitchat(
        "pet_chat",
        topics=["pets"],
        variable_dependencies=[{"variable": "has_pet", "required": True}],
    )

    session_without_var = []
    inserted_without_var = DialogLogic.insert_chitchat_into_session(
        session_without_var, [chitchat], user_model={}
    )

    session_with_var = []
    inserted_with_var = DialogLogic.insert_chitchat_into_session(
        session_with_var, [chitchat], user_model={"has_pet": True}
    )

    assert inserted_without_var is False
    assert inserted_with_var is True
    assert session_with_var == [chitchat]
