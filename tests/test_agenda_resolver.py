from nardial.agenda.items import AgendaContext, NarrativeSlot
from nardial.agenda.resolver import resolve_agenda
from nardial.agenda.slot_bounds import SlotBounds
from nardial.dialog_registry import DialogRegistry
from nardial.mini_dialogs import FunctionalDialog, NarrativeDialog


def make_functional(dialog_id, functional_type="greeting"):
    return FunctionalDialog(dialog_id=dialog_id, moves=[], type=functional_type)


def make_narrative(dialog_id, thread, position):
    return NarrativeDialog(dialog_id=dialog_id, moves=[], thread=thread, position=position)


def test_resolve_agenda_flat_string_list_yields_in_order():
    greeting = make_functional("greeting_1", functional_type="greeting")
    farewell = make_functional("farewell_1", functional_type="farewell")
    registry = DialogRegistry.build([greeting, farewell])
    context = AgendaContext(registry=registry)

    results = list(resolve_agenda(["greeting_1", "farewell_1"], context))

    assert results == [greeting, farewell]


def test_resolve_agenda_requeues_slot_until_count_min_met():
    step1 = make_narrative("thread_a_step_1", thread="thread_a", position=1)
    step2 = make_narrative("thread_a_step_2", thread="thread_a", position=2)
    registry = DialogRegistry.build([step1, step2])
    context = AgendaContext(registry=registry)

    slot = NarrativeSlot(thread="thread_a", bounds=SlotBounds(count_min=2, count_max=2))
    gen = resolve_agenda([slot], context)

    first = next(gen)
    assert first is step1
    # Second resolve only reflects the new state once mark_completed() runs.
    context.mark_completed(first.dialog_id)

    second = next(gen)
    assert second is step2
    context.mark_completed(second.dialog_id)

    results_rest = list(gen)
    assert results_rest == []


def test_resolve_agenda_none_resolving_items_are_skipped_not_requeued():
    step1 = make_narrative("thread_a_step_1", thread="thread_a", position=1)
    registry = DialogRegistry.build([step1])
    context = AgendaContext(registry=registry)

    missing_slot = NarrativeSlot(thread="does_not_exist")

    results = list(resolve_agenda([missing_slot, "thread_a_step_1"], context))

    assert results == [step1]


def test_resolve_agenda_duration_max_hard_stops_even_with_count_min_unmet(monkeypatch):
    step1 = make_narrative("thread_a_step_1", thread="thread_a", position=1)
    registry = DialogRegistry.build([step1])
    context = AgendaContext(registry=registry)

    clock = iter([0.0, 5.0])
    monkeypatch.setattr("nardial.agenda.resolver.monotonic", lambda: next(clock))

    slot = NarrativeSlot(thread="thread_a", bounds=SlotBounds(count_min=5, count_max=None, duration_max=1.0))

    results = list(resolve_agenda([slot], context))

    assert results == [step1]
