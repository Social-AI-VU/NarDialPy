"""Multi-session arc plan: designer-authored per-session agenda templates.

A ``SessionPlan`` maps session numbers to ``SessionTemplate`` objects, each
holding an agenda for that session.  ``SessionManager`` calls
``get_template(session_number)`` to pick the correct agenda automatically based
on how many sessions the participant has already completed.  If the session
number exceeds the highest defined index the last template is reused, making
open-ended longitudinal designs easy to express.

Optional ``event_handlers`` and ``event_sources`` fields let designers declare
event routing and event producers directly in the plan file so that a single
JSON document fully describes a session arc including its runtime behaviour.

JSON format::

    {
        "plan_id": "companion_study",
        "sessions": [
            {
                "session_index": 1,
                "agenda": [
                    "greeting",
                    {"type": "narrative_slot", "thread": "intro"},
                    "goodbye"
                ]
            }
        ],
        "event_sources": [
            {
                "type": "timer",
                "event_type": "check_in",
                "delay_seconds": 300,
                "repeat": true,
                "handler_dialog_id": "periodic_check_in"
            }
        ],
        "event_handlers": [
            {
                "event_type": "check_in",
                "handler_dialog_id": "periodic_check_in",
                "interrupt_level": "BETWEEN_DIALOGS",
                "resume_policy": "DISCARD"
            }
        ]
    }
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from nardial.agenda.items import AgendaItem, coerce_agenda_item
from nardial.events.specs import AnyEventSourceSpec, EventHandlerSpec

logger = logging.getLogger(__name__)


class SessionTemplate(BaseModel):
    """Agenda definition for one session in a multi-session study arc.

    Attributes
    ----------
    session_index : int
        1-based session number this template applies to.
    agenda : list[str | dict]
        Raw agenda entries; coerced to typed ``AgendaItem`` objects at
        resolution time via :meth:`get_agenda_items`.
    """

    session_index: int
    agenda: list[str | dict]

    def get_agenda_items(self) -> list[AgendaItem]:
        """Coerce all raw agenda entries to typed ``AgendaItem`` objects.

        Returns
        -------
        list[AgendaItem]
            Typed items ready to pass directly to :func:`resolve_agenda`.
        """
        return [coerce_agenda_item(item) for item in self.agenda]


class SessionPlan(BaseModel):
    """Designer-authored multi-session arc: maps session numbers to agenda templates.

    ``SessionManager`` calls :meth:`get_template` with the participant's
    current 1-based session number.  If that number exceeds the highest
    ``session_index`` in the plan, the template with the highest index is
    returned as a fallback — useful for studies where later sessions all share
    the same structure.

    The optional ``event_handlers`` and ``event_sources`` fields let designers
    declare event routing and producers in the same JSON file as the agenda.
    ``SessionManager._resolve_plan_agenda()`` registers these into the session
    at load time so no Python code is required for common interrupt patterns.

    Attributes
    ----------
    plan_id : str
        Human-readable identifier for this plan (used in log messages).
    sessions : list[SessionTemplate]
        Session templates.  Need not be sorted by ``session_index``.
    event_handlers : list[EventHandlerSpec]
        Event-type → handler-dialog mappings applied for every session in this
        plan.  Registered into ``SessionManager._event_handlers`` at load time.
    event_sources : list[AnyEventSourceSpec]
        Event producer configurations (e.g. timers, webhooks).  Instantiated
        and registered into ``SessionManager._event_sources`` at load time.
    """

    plan_id: str
    sessions: list[SessionTemplate]
    event_handlers: list[EventHandlerSpec] = Field(default_factory=list)
    event_sources: list[AnyEventSourceSpec] = Field(default_factory=list)

    def get_template(self, session_number: int) -> SessionTemplate | None:
        """Return the template for the given 1-based session number.

        Tries an exact match on ``session_index`` first.  If the session number
        exceeds the highest defined index, the template with the highest index
        is returned.  Returns ``None`` only when ``sessions`` is empty.

        Parameters
        ----------
        session_number : int
            1-based current session number (i.e. ``completed_sessions + 1``).

        Returns
        -------
        SessionTemplate | None
        """
        if not self.sessions:
            return None
        for template in self.sessions:
            if template.session_index == session_number:
                return template
        # Fallback: use the last-defined template for any session beyond the plan.
        last = max(self.sessions, key=lambda t: t.session_index)
        if session_number > last.session_index:
            return last
        return None


def load_session_plan(path: str) -> SessionPlan:
    """Load and validate a :class:`SessionPlan` from a JSON file.

    Parameters
    ----------
    path : str
        Filesystem path to the session plan JSON file.

    Returns
    -------
    SessionPlan

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    json.JSONDecodeError
        If the file is not valid JSON.
    pydantic.ValidationError
        If the JSON does not conform to the :class:`SessionPlan` schema.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    plan = SessionPlan.model_validate(data)
    logger.info(
        "Loaded SessionPlan '%s' with %d session template(s) from %s",
        plan.plan_id,
        len(plan.sessions),
        path,
    )
    return plan
