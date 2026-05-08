"""Agenda package — agenda items, resolution context, and string coercion.

Import from here for the public API:

    from nardial.agenda import AgendaItem, AgendaContext, DialogRef, coerce_agenda_item, AnyAgendaItem
"""

from nardial.agenda.items import (
    AgendaContext,
    AgendaItem,
    AnyAgendaItem,
    DialogRef,
    coerce_agenda_item,
)

__all__ = [
    "AgendaContext",
    "AgendaItem",
    "AnyAgendaItem",
    "DialogRef",
    "coerce_agenda_item",
]
