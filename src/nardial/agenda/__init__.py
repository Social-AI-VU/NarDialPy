"""Agenda package — agenda items, eligibility rules, and resolution context.

Import from here for the public API:

    from nardial.agenda import (
        AgendaItem, AgendaContext, AnyAgendaItem, coerce_agenda_item,
        DialogRef, NarrativeSlot, ChitchatSlot, FunctionalSlot, LLMDialogRef,
        SlotBounds,
        resolve_agenda,
        EligibilityPolicy, EligibilityRule,
        ExcludeIfSeenRule, DepsMetRule, VariableDepsMetRule, NarrativeOrderingRule,
    )
"""

from nardial.agenda.items import (
    AgendaContext,
    AgendaItem,
    AnyAgendaItem,
    ChitchatSlot,
    DialogRef,
    FunctionalSlot,
    LLMDialogRef,
    NarrativeSlot,
    coerce_agenda_item,
)
from nardial.agenda.resolver import resolve_agenda
from nardial.agenda.slot_bounds import SlotBounds
from nardial.eligibility import (
    DepsMetRule,
    EligibilityPolicy,
    EligibilityRule,
    ExcludeIfSeenRule,
    NarrativeOrderingRule,
    VariableDepsMetRule,
)

__all__ = [
    "AgendaContext",
    "AgendaItem",
    "AnyAgendaItem",
    "coerce_agenda_item",
    "DialogRef",
    "NarrativeSlot",
    "ChitchatSlot",
    "FunctionalSlot",
    "LLMDialogRef",
    "SlotBounds",
    "resolve_agenda",
    "DepsMetRule",
    "EligibilityPolicy",
    "EligibilityRule",
    "ExcludeIfSeenRule",
    "NarrativeOrderingRule",
    "VariableDepsMetRule",
]
