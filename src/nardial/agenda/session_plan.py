import json
from typing import Any, Dict, List, Optional, Tuple


class SessionTemplate:
    """The agenda to run for one specific session number in a `SessionPlan`."""

    def __init__(self, session_index: int, agenda: Optional[list] = None):
        self.session_index = session_index
        self.agenda = list(agenda or [])

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionTemplate":
        return cls(session_index=data["session_index"], agenda=list(data.get("agenda") or []))

    def to_dict(self) -> Dict[str, Any]:
        return {"session_index": self.session_index, "agenda": list(self.agenda)}

    def validate(self) -> List[str]:
        errs: List[str] = []
        if not isinstance(self.session_index, int) or isinstance(self.session_index, bool):
            errs.append("session_index must be an integer")
        elif self.session_index < 1:
            errs.append("session_index must be >= 1")
        if not isinstance(self.agenda, list):
            errs.append("agenda must be a list")
        return errs


class SessionPlan:
    """An ordered set of per-session-number agenda templates.

    `get_template()` picks the exact `session_index` match when one exists,
    otherwise falls back to the highest-indexed template as a steady-state
    agenda for every session beyond the plan's explicitly authored ones.
    """

    def __init__(self, plan_id: str, sessions: Optional[List[SessionTemplate]] = None):
        self.plan_id = plan_id
        self.sessions = list(sessions or [])

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionPlan":
        return cls(
            plan_id=data.get("plan_id"),
            sessions=[SessionTemplate.from_dict(s) for s in data.get("sessions") or []],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"plan_id": self.plan_id, "sessions": [s.to_dict() for s in self.sessions]}

    def validate(self) -> List[str]:
        errs: List[str] = []
        if not isinstance(self.plan_id, str) or not self.plan_id:
            errs.append("plan_id must be a non-empty string")
        if not self.sessions:
            errs.append("sessions must be a non-empty list")

        seen_indexes = set()
        for i, template in enumerate(self.sessions):
            errs.extend(f"sessions[{i}]: {err}" for err in template.validate())
            if template.session_index in seen_indexes:
                errs.append(f"sessions[{i}]: duplicate session_index {template.session_index}")
            seen_indexes.add(template.session_index)
        return errs

    def get_template(self, session_number: int) -> Optional[SessionTemplate]:
        """Return the template for `session_number` (1-indexed).

        Exact `session_index` match wins; otherwise the highest-indexed
        template is returned as the steady-state fallback. `None` only when
        the plan defines no templates at all.
        """
        if not self.sessions:
            return None
        for template in self.sessions:
            if template.session_index == session_number:
                return template
        return max(self.sessions, key=lambda t: t.session_index)


def load_session_plan(path: str) -> Tuple[Optional[SessionPlan], List[str]]:
    """Load a SessionPlan from a JSON file. Returns (plan, errors); never raises."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return None, [f"{path}: {e}"]

    try:
        plan = SessionPlan.from_dict(data)
    except Exception as e:
        return None, [f"{path}: {e}"]

    return plan, plan.validate()
