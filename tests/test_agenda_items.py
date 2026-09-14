import random

import pytest

from nardial.agenda.items import (
    AgendaContext,
    AgendaItem,
    ChitchatSlot,
    DialogRef,
    FunctionalSlot,
    LLMDialogRef,
    NarrativeSlot,
    coerce_agenda_item,
)
from nardial.agenda.slot_bounds import SlotBounds
from nardial.dialog_registry import DialogRegistry
from nardial.mini_dialogs import ChitchatDialog, FunctionalDialog, LLMDialog, NarrativeDialog


def make_llm_dialog(dialog_id, prompt="hi", max_turns=3, duration=None):
    return LLMDialog(dialog_id=dialog_id, moves=[], prompt=prompt, max_turns=max_turns, duration=duration)


def make_functional(dialog_id, functional_type="greeting"):
    return FunctionalDialog(dialog_id=dialog_id, moves=[], type=functional_type)


def make_narrative(dialog_id, thread, position):
    return NarrativeDialog(dialog_id=dialog_id, moves=[], thread=thread, position=position)


def make_chitchat(dialog_id, topics=None, variable_dependencies=None):
    return ChitchatDialog(dialog_id=dialog_id, moves=[], topics=topics, variable_dependencies=variable_dependencies)


def test_coerce_agenda_item_from_string():
    item = coerce_agenda_item("greeting_1")

    assert isinstance(item, DialogRef)
    assert item.id == "greeting_1"


def test_coerce_agenda_item_from_dialog_ref_dict():
    item = coerce_agenda_item({"type": "dialog_ref", "id": "greeting_1"})

    assert isinstance(item, DialogRef)
    assert item.id == "greeting_1"


def test_coerce_agenda_item_passes_through_agenda_item_instances():
    original = DialogRef(id="greeting_1")

    assert coerce_agenda_item(original) is original


def test_coerce_agenda_item_rejects_unknown_dict_type():
    with pytest.raises(ValueError):
        coerce_agenda_item({"type": "not_a_real_type"})


def test_coerce_agenda_item_rejects_unsupported_value():
    with pytest.raises(ValueError):
        coerce_agenda_item(123)


def test_dialog_ref_resolves_hit():
    greeting = make_functional("greeting_1")
    registry = DialogRegistry.build([greeting])
    context = AgendaContext(registry=registry)

    assert DialogRef(id="greeting_1").resolve(context) is greeting


def test_dialog_ref_resolves_miss_warns_and_returns_none(caplog):
    registry = DialogRegistry.build([])
    context = AgendaContext(registry=registry)

    with caplog.at_level("WARNING"):
        result = DialogRef(id="missing").resolve(context)

    assert result is None
    assert "missing" in caplog.text


def test_dialog_ref_resolves_none_without_registry():
    context = AgendaContext(registry=None)

    assert DialogRef(id="greeting_1").resolve(context) is None


def test_agenda_context_mark_completed_updates_both_sets():
    context = AgendaContext()

    context.mark_completed("greeting_1")

    assert context.completed_ids == ["greeting_1"]
    assert context.session_completed_ids == ["greeting_1"]


def test_agenda_context_mark_completed_is_idempotent():
    context = AgendaContext()

    context.mark_completed("greeting_1")
    context.mark_completed("greeting_1")

    assert context.completed_ids == ["greeting_1"]
    assert context.session_completed_ids == ["greeting_1"]


def test_agenda_item_is_abstract():
    with pytest.raises(TypeError):
        AgendaItem()


def test_narrative_slot_resolves_lowest_eligible_position():
    step1 = make_narrative("thread_a_step_1", thread="thread_a", position=1)
    step2 = make_narrative("thread_a_step_2", thread="thread_a", position=2)
    registry = DialogRegistry.build([step1, step2])
    context = AgendaContext(registry=registry)

    assert NarrativeSlot(thread="thread_a").resolve(context) is step1

    context.mark_completed("thread_a_step_1")
    assert NarrativeSlot(thread="thread_a").resolve(context) is step2


def test_narrative_slot_breaks_ties_randomly():
    tied_a = make_narrative("thread_a_step_1a", thread="thread_a", position=1)
    tied_b = make_narrative("thread_a_step_1b", thread="thread_a", position=1)
    registry = DialogRegistry.build([tied_a, tied_b])
    context = AgendaContext(registry=registry)

    random.seed(0)
    results = {NarrativeSlot(thread="thread_a").resolve(context).dialog_id for _ in range(20)}

    assert results == {"thread_a_step_1a", "thread_a_step_1b"}


def test_narrative_slot_no_candidates_warns_and_returns_none(caplog):
    registry = DialogRegistry.build([])
    context = AgendaContext(registry=registry)

    with caplog.at_level("WARNING"):
        result = NarrativeSlot(thread="missing_thread").resolve(context)

    assert result is None
    assert "missing_thread" in caplog.text


def test_narrative_slot_no_registry_warns_and_returns_none(caplog):
    context = AgendaContext(registry=None)

    with caplog.at_level("WARNING"):
        result = NarrativeSlot(thread="thread_a").resolve(context)

    assert result is None


def test_coerce_agenda_item_from_narrative_slot_dict():
    item = coerce_agenda_item({"type": "narrative_slot", "thread": "thread_a", "bounds": {"count_min": 2, "count_max": 3}})

    assert isinstance(item, NarrativeSlot)
    assert item.thread == "thread_a"
    assert item.bounds.count_min == 2
    assert item.bounds.count_max == 3


def test_coerce_agenda_item_narrative_slot_default_bounds():
    item = coerce_agenda_item({"type": "narrative_slot", "thread": "thread_a"})

    assert isinstance(item.bounds, SlotBounds)
    assert item.bounds.to_dict() == SlotBounds().to_dict()


def test_chitchat_slot_picks_highest_topic_overlap():
    low_overlap = make_chitchat("low_overlap", topics=["pizza"])
    high_overlap = make_chitchat("high_overlap", topics=["pizza", "pasta"])
    no_overlap = make_chitchat("no_overlap", topics=["weather"])
    registry = DialogRegistry.build([low_overlap, high_overlap, no_overlap])
    context = AgendaContext(registry=registry, topics_of_interest=["pizza", "pasta"])

    assert ChitchatSlot().resolve(context) is high_overlap


def test_chitchat_slot_topics_filter_restricts_candidates():
    pizza = make_chitchat("pizza_chat", topics=["pizza"])
    weather = make_chitchat("weather_chat", topics=["weather"])
    registry = DialogRegistry.build([pizza, weather])
    context = AgendaContext(registry=registry)

    result = ChitchatSlot(topics_filter=["pizza"]).resolve(context)

    assert result is pizza


def test_chitchat_slot_no_eligible_candidates_warns_and_returns_none(caplog):
    registry = DialogRegistry.build([])
    context = AgendaContext(registry=registry)

    with caplog.at_level("WARNING"):
        result = ChitchatSlot().resolve(context)

    assert result is None


def test_chitchat_slot_respects_real_user_model_via_variable_dependency_rule():
    """Regression: the pre-agenda chitchat-selection helper this replaced hardcoded
    user_model={}, so a VariableDependencyMetRule could never actually block selection."""
    gated = make_chitchat(
        "pet_chat",
        topics=["pets"],
        variable_dependencies=[{"variable": "has_pet", "required": True}],
    )
    registry = DialogRegistry.build([gated])

    context_without_var = AgendaContext(registry=registry, user_model={})
    assert ChitchatSlot().resolve(context_without_var) is None

    context_with_var = AgendaContext(registry=registry, user_model={"has_pet": True})
    assert ChitchatSlot().resolve(context_with_var) is gated


def test_coerce_agenda_item_from_chitchat_slot_dict():
    item = coerce_agenda_item({"type": "chitchat_slot", "topics_filter": ["pizza"], "bounds": {"count_max": 2}})

    assert isinstance(item, ChitchatSlot)
    assert item.topics_filter == ["pizza"]
    assert item.bounds.count_max == 2


def test_functional_slot_resolves_correct_type():
    greeting = make_functional("greeting_1", functional_type="greeting")
    farewell = make_functional("farewell_1", functional_type="farewell")
    registry = DialogRegistry.build([greeting, farewell])
    context = AgendaContext(registry=registry)

    assert FunctionalSlot(functional_type="greeting").resolve(context) is greeting
    assert FunctionalSlot(functional_type="farewell").resolve(context) is farewell


def test_functional_slot_still_resolves_when_already_completed():
    """Regression: FunctionalDialog.DEFAULT_ELIGIBILITY deliberately has no
    ExcludeIfSeenRule, so greetings/farewells re-run every session."""
    greeting = make_functional("greeting_1", functional_type="greeting")
    registry = DialogRegistry.build([greeting])
    context = AgendaContext(registry=registry, completed_ids=["greeting_1"])

    assert FunctionalSlot(functional_type="greeting").resolve(context) is greeting


def test_functional_slot_no_candidates_warns_and_returns_none(caplog):
    registry = DialogRegistry.build([])
    context = AgendaContext(registry=registry)

    with caplog.at_level("WARNING"):
        result = FunctionalSlot(functional_type="greeting").resolve(context)

    assert result is None


def test_coerce_agenda_item_from_functional_slot_dict():
    item = coerce_agenda_item({"type": "functional_slot", "functional_type": "greeting"})

    assert isinstance(item, FunctionalSlot)
    assert item.functional_type == "greeting"


def test_llm_dialog_ref_resolves_hit():
    dialog = make_llm_dialog("llm_1")
    registry = DialogRegistry.build([dialog])
    context = AgendaContext(registry=registry)

    assert LLMDialogRef(id="llm_1").resolve(context) is dialog


def test_llm_dialog_ref_missing_id_warns_and_returns_none(caplog):
    registry = DialogRegistry.build([])
    context = AgendaContext(registry=registry)

    with caplog.at_level("WARNING"):
        result = LLMDialogRef(id="missing").resolve(context)

    assert result is None
    assert "missing" in caplog.text


def test_llm_dialog_ref_wrong_type_warns_and_returns_none(caplog):
    greeting = make_functional("greeting_1")
    registry = DialogRegistry.build([greeting])
    context = AgendaContext(registry=registry)

    with caplog.at_level("WARNING"):
        result = LLMDialogRef(id="greeting_1").resolve(context)

    assert result is None
    assert "greeting_1" in caplog.text


def test_llm_dialog_ref_override_produces_distinct_copy():
    dialog = make_llm_dialog("llm_1", max_turns=3, duration=None)
    registry = DialogRegistry.build([dialog])
    context = AgendaContext(registry=registry)

    result = LLMDialogRef(id="llm_1", max_turns=7, duration=30.0).resolve(context)

    assert result is not dialog
    assert result.max_turns == 7
    assert result.duration == 30.0
    assert dialog.max_turns == 3
    assert dialog.duration is None


def test_llm_dialog_ref_without_overrides_returns_original():
    dialog = make_llm_dialog("llm_1")
    registry = DialogRegistry.build([dialog])
    context = AgendaContext(registry=registry)

    assert LLMDialogRef(id="llm_1").resolve(context) is dialog


def test_coerce_agenda_item_from_llm_dialog_ref_dict():
    item = coerce_agenda_item({"type": "llm_dialog_ref", "id": "llm_1", "max_turns": 5})

    assert isinstance(item, LLMDialogRef)
    assert item.id == "llm_1"
    assert item.max_turns == 5
    assert item.duration is None
