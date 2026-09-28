from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Optional, Type, Union

if TYPE_CHECKING:
    from nardial.agenda.items import AgendaContext
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
    # 1-indexed number of the current session, when known.
    session_index: Optional[int] = None


class EligibilityRule(ABC):
    # Name used in JSON rule specs; set by `@register_rule`.
    RULE_NAME: Optional[str] = None

    @abstractmethod
    def is_eligible(self, dialog: "MiniDialog", context: EligibilityContext) -> bool:
        ...

    @classmethod
    def from_dict(cls, params: Dict[str, Any]) -> "EligibilityRule":
        """Build a rule from the params of a JSON rule spec (everything but `"rule"`).

        The default passes params straight to the constructor; override it when
        a param needs converting (e.g. a string to an enum).
        """
        return cls(**params)

    def to_dict(self) -> Dict[str, Any]:
        """Inverse of `from_dict`, including the `"rule"` name. Override to add params."""
        return {"rule": self.RULE_NAME}


_RULES: Dict[str, Type[EligibilityRule]] = {}


def register_rule(name: str) -> Callable[[Type[EligibilityRule]], Type[EligibilityRule]]:
    """Class decorator registering an `EligibilityRule` under `name` for JSON rule specs.

    Sets `cls.RULE_NAME = name`. Re-registering the same class is a no-op;
    registering a different class under a taken name raises `ValueError`.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("rule name must be a non-empty string")

    def decorator(cls: Type[EligibilityRule]) -> Type[EligibilityRule]:
        existing = _RULES.get(name)
        if existing is not None and existing is not cls:
            raise ValueError(f"eligibility rule {name!r} is already registered to {existing.__name__}")
        cls.RULE_NAME = name
        _RULES[name] = cls
        return cls

    return decorator


def get_rule(name: str) -> Optional[Type[EligibilityRule]]:
    return _RULES.get(name)


def rule_names() -> List[str]:
    return list(_RULES)


def build_rule(spec: Union[str, Dict[str, Any]]) -> EligibilityRule:
    """Build a rule from a JSON spec: a rule name, or `{"rule": name, **params}`.

    Raises `ValueError` for an unknown rule or params the rule doesn't accept.
    """
    if isinstance(spec, str):
        name, params = spec, {}
    elif isinstance(spec, dict) and isinstance(spec.get("rule"), str):
        name = spec["rule"]
        params = {k: v for k, v in spec.items() if k != "rule"}
    else:
        raise ValueError(f"rule spec must be a rule name or an object with a 'rule' name, got {spec!r}")

    rule_cls = _RULES.get(name)
    if rule_cls is None:
        raise ValueError(f"unknown eligibility rule {name!r}; known rules: {', '.join(rule_names())}")
    try:
        return rule_cls.from_dict(params)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid params for eligibility rule {name!r}: {exc}") from exc


@register_rule("exclude_if_seen")
class ExcludeIfSeenRule(EligibilityRule):
    """Ineligible once the dialog's id has already been completed.

    `scope=PARTICIPANT` (default) checks the cross-session completed set;
    `scope=SESSION` checks only dialogs completed earlier in this session.
    """

    def __init__(self, scope: EligibilityScope = EligibilityScope.PARTICIPANT):
        self.scope = scope

    @classmethod
    def from_dict(cls, params: Dict[str, Any]) -> "ExcludeIfSeenRule":
        params = dict(params)
        if "scope" in params:
            params["scope"] = EligibilityScope(params["scope"])
        return cls(**params)

    def to_dict(self) -> Dict[str, Any]:
        return {**super().to_dict(), "scope": self.scope.value}

    def is_eligible(self, dialog: "MiniDialog", context: EligibilityContext) -> bool:
        seen_ids = context.session_completed_ids if self.scope == EligibilityScope.SESSION else context.completed_ids
        return dialog.dialog_id not in set(seen_ids)


@register_rule("dependency_met")
class DependencyMetRule(EligibilityRule):
    """Ineligible unless every id in `dialog.dependencies` has been completed."""

    def is_eligible(self, dialog: "MiniDialog", context: EligibilityContext) -> bool:
        deps = getattr(dialog, "dependencies", []) or []
        completed = set(context.completed_ids)
        return all(dep in completed for dep in deps)


@register_rule("variable_dependency_met")
class VariableDependencyMetRule(EligibilityRule):
    """Ineligible unless every required variable dependency is present in the user model."""

    def is_eligible(self, dialog: "MiniDialog", context: EligibilityContext) -> bool:
        for var_dep in getattr(dialog, "variable_dependencies", None) or []:
            variable = var_dep["variable"]
            required = var_dep.get("required", True)
            if required and not context.user_model.get(variable):
                return False
        return True


@register_rule("narrative_ordering")
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


def is_dialog_eligible(dialog: "MiniDialog", context: "AgendaContext",
                        policy: Optional[EligibilityPolicy] = None) -> bool:
    """Determine whether `dialog` can run right now.

    Delegates to `policy` if given, otherwise the dialog class's own
    `DEFAULT_ELIGIBILITY` rules (see `mini_dialogs.py`). Operates directly on
    an `AgendaContext` (or any object exposing the same `registry`/
    `completed_ids`/`session_completed_ids`/`user_model` attributes -- this
    module never imports `AgendaContext` at runtime, only for type hints, to
    avoid a cycle with `agenda/items.py`). Replaces the legacy flat
    `(dialog, completed_ids, user_model, all_dialogs)` signature previously
    exposed via a now-removed static helper class.
    """
    effective_policy = policy or EligibilityPolicy(list(getattr(type(dialog), "DEFAULT_ELIGIBILITY", [])))
    return effective_policy.is_eligible(dialog, context)
