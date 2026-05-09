"""Multi-session arc plan: designer-authored per-session agenda templates.

A ``SessionPlan`` maps session numbers to ``SessionTemplate`` objects, each
holding an agenda for that session.  ``SessionManager`` calls
``get_template(session_number)`` to pick the correct agenda automatically based
on how many sessions the participant has already completed.  If the session
number exceeds the highest defined index the last template is reused, making
open-ended longitudinal designs easy to express.

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
            },
            {
                "session_index": 2,
                "agenda": [
                    "greeting",
                    {"type": "chitchat_slot"},
                    {"type": "narrative_slot", "thread": "intro", "bounds": {"count_min": 2, "count_max": 2}},
                    "goodbye"
                ]
            }
        ]
    }
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from nardial.agenda.items import AgendaItem, coerce_agenda_item

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

    Attributes
    ----------
    plan_id : str
        Human-readable identifier for this plan (used in log messages).
    sessions : list[SessionTemplate]
        Session templates.  Need not be sorted by ``session_index``.
    """

    plan_id: str
    sessions: list[SessionTemplate]

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
