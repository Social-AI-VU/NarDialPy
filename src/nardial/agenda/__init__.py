"""Agenda package — agenda items, eligibility rules, and resolution context.

Import from here for the public API:

    from nardial.agenda import (
        AgendaItem, AgendaContext, DialogRef, coerce_agenda_item, AnyAgendaItem,
        EligibilityPolicy, EligibilityRule,
        ExcludeIfSeenRule, DepsMetRule, VariableDepsMetRule, NarrativeOrderingRule,
    )
"""

from nardial.agenda.items import (
    AgendaContext,
    AgendaItem,
    AnyAgendaItem,
    DialogRef,
    coerce_agenda_item,
)
from nardial.agenda.rules import (
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
    "DialogRef",
    "coerce_agenda_item",
    "DepsMetRule",
    "EligibilityPolicy",
    "EligibilityRule",
    "ExcludeIfSeenRule",
    "NarrativeOrderingRule",
    "VariableDepsMetRule",
]
