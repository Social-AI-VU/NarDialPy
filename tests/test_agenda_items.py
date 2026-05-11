"""Tests for AgendaItem, DialogRef, AgendaContext, and to_agenda_item."""

import pytest
from pydantic import ValidationError

from nardial.agenda.items import (
    AgendaContext,
    AgendaItem,
    DialogRef,
    to_agenda_item,
)
from nardial.dialog_registry import DialogRegistry
from nardial.mini_dialogs import NarrativeDialog, ChitchatDialog
from nardial.moves import MoveSay


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_registry(*dialogs):
    return DialogRegistry.build(list(dialogs))


def make_narrative(dialog_id, thread="main", position=1):
    return NarrativeDialog(dialog_id=dialog_id, moves=[], thread=thread, position=position)


def make_context(registry=None, completed_ids=None, session_completed_ids=None):
    return AgendaContext(
        registry=registry or make_registry(),
        completed_ids=set(completed_ids or []),
        session_completed_ids=set(session_completed_ids or []),
    )


# ── AgendaItem is abstract ────────────────────────────────────────────────────

class TestAgendaItemIsAbstract:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            AgendaItem()  # type: ignore[abstract]

    def test_subclass_without_resolve_is_abstract(self):
        class Incomplete(AgendaItem):
            pass
        with pytest.raises(TypeError):
            Incomplete()


# ── DialogRef construction ────────────────────────────────────────────────────

class TestDialogRef:
    def test_default_type_field(self):
        ref = DialogRef(id="greeting")
        assert ref.type == "dialog_ref"

    def test_id_stored(self):
        ref = DialogRef(id="intro")
        assert ref.id == "intro"

    def test_from_dict(self):
        ref = DialogRef.model_validate({"type": "dialog_ref", "id": "greeting"})
        assert ref.id == "greeting"

    def test_missing_id_raises(self):
        with pytest.raises(ValidationError):
            DialogRef.model_validate({"type": "dialog_ref"})


# ── DialogRef.resolve ─────────────────────────────────────────────────────────

class TestDialogRefResolve:
    def test_resolve_returns_matching_dialog(self):
        n = make_narrative("n1")
        ctx = make_context(registry=make_registry(n))
        ref = DialogRef(id="n1")
        assert ref.resolve(ctx) is n

    def test_resolve_returns_none_for_missing_id(self, caplog):
        ctx = make_context(registry=make_registry())
        ref = DialogRef(id="nonexistent")
        import logging
        with caplog.at_level(logging.WARNING):
            result = ref.resolve(ctx)
        assert result is None
        assert "nonexistent" in caplog.text

    def test_resolve_warns_on_missing(self, caplog):
        ctx = make_context(registry=make_registry())
        import logging
        with caplog.at_level(logging.WARNING):
            DialogRef(id="ghost").resolve(ctx)
        assert "ghost" in caplog.text


# ── AgendaContext construction ────────────────────────────────────────────────

class TestAgendaContext:
    def test_minimal_construction(self):
        reg = make_registry()
        ctx = AgendaContext(registry=reg)
        assert ctx.registry is reg
        assert ctx.completed_ids == set()
        assert ctx.session_completed_ids == set()
        assert ctx.user_model == {}
        assert ctx.topics_of_interest == []

    def test_completed_ids_populated(self):
        ctx = make_context(completed_ids=["a", "b"])
        assert "a" in ctx.completed_ids
        assert "b" in ctx.completed_ids

    def test_session_completed_ids_independent_from_completed_ids(self):
        ctx = AgendaContext(
            registry=make_registry(),
            completed_ids={"cross_session"},
            session_completed_ids={"in_session"},
        )
        assert "cross_session" in ctx.completed_ids
        assert "in_session" in ctx.session_completed_ids
        assert "cross_session" not in ctx.session_completed_ids

    def test_user_model_stored(self):
        ctx = AgendaContext(registry=make_registry(), user_model={"name": "Alice"})
        assert ctx.user_model["name"] == "Alice"

    def test_topics_of_interest_stored(self):
        ctx = AgendaContext(registry=make_registry(), topics_of_interest=["food", "travel"])
        assert "food" in ctx.topics_of_interest


# ── to_agenda_item ────────────────────────────────────────────────────────

class TestCoerceAgendaItem:
    def test_string_becomes_dialog_ref(self):
        item = to_agenda_item("greeting")
        assert isinstance(item, DialogRef)
        assert item.id == "greeting"

    def test_dict_with_dialog_ref_type_parsed(self):
        item = to_agenda_item({"type": "dialog_ref", "id": "greeting"})
        assert isinstance(item, DialogRef)
        assert item.id == "greeting"

    def test_string_and_dict_produce_equivalent_refs(self):
        by_str = to_agenda_item("greeting")
        by_dict = to_agenda_item({"type": "dialog_ref", "id": "greeting"})
        assert by_str.id == by_dict.id
        assert type(by_str) is type(by_dict)

    def test_agenda_item_passthrough(self):
        ref = DialogRef(id="existing")
        result = to_agenda_item(ref)
        assert result is ref

    def test_unknown_type_raises_validation_error(self):
        with pytest.raises((ValidationError, Exception)):
            to_agenda_item({"type": "unknown_future_type", "id": "x"})

    def test_invalid_type_raises_type_error(self):
        with pytest.raises(TypeError):
            to_agenda_item(42)  # type: ignore[arg-type]
