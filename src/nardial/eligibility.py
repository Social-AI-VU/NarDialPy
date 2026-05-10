"""Eligibility rules and EligibilityPolicy for agenda-based dialog selection.

Rules are composable predicates that together decide whether a dialog may run
given the current ``AgendaContext``.  ``EligibilityPolicy`` combines a list of
rules with short-circuit ``all()`` evaluation.

This module lives at the package root (not inside ``agenda/``) so that
``mini_dialogs.py`` can import from it without creating a layer inversion.
Each dialog class sets its own ``DEFAULT_ELIGIBILITY`` class attribute using
the classes defined here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from nardial.base_dialog import BaseDialog
    from nardial.agenda.items import AgendaContext


# ── Base ──────────────────────────────────────────────────────────────────────

class EligibilityRule(ABC):
    """Single eligibility predicate evaluated against a dialog and its context.

    Implement ``is_eligible`` to return ``False`` the moment the dialog fails
    the rule.  Rules are designed to be stateless and reusable across many
    policy instances.
    """

    @abstractmethod
    def is_eligible(self, dialog: "BaseDialog", context: "AgendaContext") -> bool:
        """Return True if the dialog passes this rule, False if it is blocked.

        Parameters
        ----------
        dialog : BaseDialog
            The candidate dialog being evaluated.
        context : AgendaContext
            Current session state, including registry, completion history, and
            user model.

        Returns
        -------
        bool
        """


# ── Concrete rules ────────────────────────────────────────────────────────────

class ExcludeIfSeenRule(EligibilityRule):
    """Block dialogs that have already been run.

    Parameters
    ----------
    scope : {"participant", "session"}
        ``"participant"`` (default) — checks ``AgendaContext.completed_ids``,
        which spans all previous sessions for this participant.
        ``"session"`` — checks ``AgendaContext.session_completed_ids``, so a
        dialog that ran in a prior session can run again in the current one.
    """

    def __init__(self, scope: Literal["participant", "session"] = "participant") -> None:
        self.scope = scope

    def is_eligible(self, dialog: "BaseDialog", context: "AgendaContext") -> bool:
        """Return False if the dialog has already been seen within the configured scope."""
        if self.scope == "session":
            return dialog.dialog_id not in context.session_completed_ids
        return dialog.dialog_id not in context.completed_ids


class DepsMetRule(EligibilityRule):
    """Block dialogs whose declared dependencies have not yet been completed.

    All IDs in ``dialog.dependencies`` must appear in
    ``AgendaContext.completed_ids`` (cross-session history + in-session
    completions) for the dialog to be eligible.
    """

    def is_eligible(self, dialog: "BaseDialog", context: "AgendaContext") -> bool:
        """Return False if any declared dependency is absent from completed_ids."""
        return all(dep in context.completed_ids for dep in dialog.dependencies)


class VariableDepsMetRule(EligibilityRule):
    """Block dialogs whose required user-model variables are not yet set.

    Variable dependencies are stored as dicts ``{"variable": str, "required": bool}``
    on each dialog.  This rule checks only those with ``required=True`` against
    ``AgendaContext.user_model``.

    This replaces the latent bug in the old ``insert_chitchat_into_session``
    that always passed ``user_model={}`` and silently skipped variable checks.
    """

    def is_eligible(self, dialog: "BaseDialog", context: "AgendaContext") -> bool:
        """Return False if any required variable is missing or falsy in user_model."""
        user_model = context.user_model or {}
        for var_dep in dialog.variable_dependencies:
            # variable_dependencies are stored as plain dicts on dialog instances.
            var = var_dep["variable"]
            required = var_dep.get("required", True)
            if required and not user_model.get(var):
                return False
        return True


class NarrativeOrderingRule(EligibilityRule):
    """Enforce sequential ordering within a narrative thread.

    Any dialog that carries ``thread`` and ``position`` attributes is treated as
    thread-ordered.  A dialog at position N is blocked if any sibling in the
    same thread with a lower position has not yet been completed.

    Uses ``AgendaContext.registry`` for O(1) sibling lookup instead of a linear
    scan.  Non-thread-ordered dialogs (those without ``thread``/``position``)
    always pass this rule.

    Duck-typing rather than ``isinstance`` keeps this module free of any import
    from ``mini_dialogs``, which in turn lets ``mini_dialogs`` import from here
    at module level without creating a circular dependency.
    """

    def is_eligible(self, dialog: "BaseDialog", context: "AgendaContext") -> bool:
        """Return False if an earlier step in the same thread is incomplete."""
        thread = getattr(dialog, "thread", None)
        position = getattr(dialog, "position", None)
        if thread is None or position is None:
            return True  # not a thread-ordered dialog
        siblings = context.registry.get_by_attr("thread", thread)
        for sibling in siblings:
            sibling_position = getattr(sibling, "position", None)
            if (
                sibling_position is not None
                and sibling_position < position
                and sibling.dialog_id not in context.completed_ids
            ):
                return False
        return True


# ── Policy ────────────────────────────────────────────────────────────────────

class EligibilityPolicy:
    """Ordered list of rules evaluated with short-circuit ``all()``.

    A dialog is eligible only when every rule in the policy returns True.
    Rules are evaluated left to right; the first False short-circuits the rest.

    Parameters
    ----------
    rules : list[EligibilityRule]
        Ordered list of predicates to evaluate.
    """

    def __init__(self, rules: list[EligibilityRule]) -> None:
        self.rules = rules

    def is_eligible(self, dialog: "BaseDialog", context: "AgendaContext") -> bool:
        """Return True if the dialog passes every rule in the policy.

        Parameters
        ----------
        dialog : BaseDialog
            Candidate dialog to evaluate.
        context : AgendaContext
            Current session state.

        Returns
        -------
        bool
        """
        return all(rule.is_eligible(dialog, context) for rule in self.rules)

    def __repr__(self) -> str:
        rule_names = ", ".join(type(r).__name__ for r in self.rules)
        return f"EligibilityPolicy([{rule_names}])"
