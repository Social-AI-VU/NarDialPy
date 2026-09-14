import pytest

from nardial.agenda.items import AgendaContext, AgendaItem, DialogRef, coerce_agenda_item
from nardial.dialog_registry import DialogRegistry
from nardial.mini_dialogs import FunctionalDialog


def make_functional(dialog_id, functional_type="greeting"):
    return FunctionalDialog(dialog_id=dialog_id, moves=[], type=functional_type)


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
