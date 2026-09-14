from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional

if TYPE_CHECKING:
    from nardial.dialog_registry import DialogRegistry
    from nardial.mini_dialogs import MiniDialog


class EligibilityScope(Enum):
    SESSION = "session"
    PARTICIPANT = "participant"


@dataclass
class EligibilityContext:
    """Minimal context eligibility rules need to evaluate a dialog.

    Stands in for the richer `AgendaContext` added in a later step, which
    exposes the same attribute names so rules never need to change when
    callers swap one context type for the other.
    """
    registry: Optional["DialogRegistry"] = None
    completed_ids: Iterable[str] = field(default_factory=list)
    session_completed_ids: Iterable[str] = field(default_factory=list)
    user_model: Dict[str, Any] = field(default_factory=dict)


class EligibilityRule(ABC):
    @abstractmethod
    def is_eligible(self, dialog: "MiniDialog", context: EligibilityContext) -> bool:
        ...


class ExcludeIfSeenRule(EligibilityRule):
    """Ineligible once the dialog's id has already been completed.

    `scope=PARTICIPANT` (default) checks the cross-session completed set;
    `scope=SESSION` checks only dialogs completed earlier in this session.
    """

    def __init__(self, scope: EligibilityScope = EligibilityScope.PARTICIPANT):
        self.scope = scope

    def is_eligible(self, dialog: "MiniDialog", context: EligibilityContext) -> bool:
        seen_ids = context.session_completed_ids if self.scope == EligibilityScope.SESSION else context.completed_ids
        return dialog.dialog_id not in set(seen_ids)


class DependencyMetRule(EligibilityRule):
    """Ineligible unless every id in `dialog.dependencies` has been completed."""

    def is_eligible(self, dialog: "MiniDialog", context: EligibilityContext) -> bool:
        deps = getattr(dialog, "dependencies", []) or []
        completed = set(context.completed_ids)
        return all(dep in completed for dep in deps)


class VariableDependencyMetRule(EligibilityRule):
    """Ineligible unless every required variable dependency is present in the user model."""

    def is_eligible(self, dialog: "MiniDialog", context: EligibilityContext) -> bool:
        for var_dep in getattr(dialog, "variable_dependencies", None) or []:
            variable = var_dep["variable"]
            required = var_dep.get("required", True)
            if required and not context.user_model.get(variable):
                return False
        return True


class NarrativeOrderingRule(EligibilityRule):
    """Ineligible if an earlier, not-yet-completed position exists in the same thread.

    Duck-types via `getattr(dialog, "thread"/"position", None)` and looks up
    siblings through `context.registry.get_by_attr(...)` rather than
    `isinstance(dialog, NarrativeDialog)` — this is what lets `eligibility.py`
    avoid importing `mini_dialogs.py` at runtime (see module docstring).
    """

    def is_eligible(self, dialog: "MiniDialog", context: EligibilityContext) -> bool:
        thread = getattr(dialog, "thread", None)
        position = getattr(dialog, "position", None)
        if thread is None or position is None or context.registry is None:
            return True

        completed = set(context.completed_ids)
        for sibling in context.registry.get_by_attr("thread", thread):
            sibling_position = getattr(sibling, "position", None)
            if sibling_position is None:
                continue
            if sibling_position < position and sibling.dialog_id not in completed:
                return False
        return True


class EligibilityPolicy:
    def __init__(self, rules: Optional[List[EligibilityRule]] = None):
        self.rules = list(rules or [])

    def is_eligible(self, dialog: "MiniDialog", context: EligibilityContext) -> bool:
        return all(rule.is_eligible(dialog, context) for rule in self.rules)
