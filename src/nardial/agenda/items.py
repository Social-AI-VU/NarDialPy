"""Agenda item types and the shared context passed to every resolve() call.

Item types: ``DialogRef``, ``NarrativeSlot``, ``ChitchatSlot``,
``FunctionalSlot``, ``LLMDialogRef``.  Use ``coerce_agenda_item`` to normalise
a raw string, dict, or AgendaItem to a typed instance.
"""

from __future__ import annotations

import copy
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from nardial.agenda.slot_bounds import SlotBounds
from nardial.eligibility import EligibilityPolicy
from nardial.mini_dialogs import (
    ChitchatDialog,
    DialogType,
    FunctionalDialog,
    LLMDialog,
    NarrativeDialog,
)

if TYPE_CHECKING:
    from nardial.base_dialog import BaseDialog
    from nardial.dialog_registry import DialogRegistry

logger = logging.getLogger(__name__)


# ── Context ───────────────────────────────────────────────────────────────────

@dataclass
class AgendaContext:
    """Shared context passed to every ``AgendaItem.resolve()`` call.

    Attributes
    ----------
    registry : DialogRegistry
        Indexed pool of all loaded dialogs.
    completed_ids : set[str]
        Cross-session history: dialog IDs completed in any previous session
        plus those already completed in the current session.
    session_completed_ids : set[str]
        In-session completions only; starts empty at the beginning of each
        session so ``ExcludeIfSeenRule(scope="session")`` can distinguish
        within-session from cross-session state.
    user_model : Any
        UserModel instance or plain dict of user variables.
    topics_of_interest : list[str]
        User interest keywords accumulated during the session.
    """

    registry: "DialogRegistry"
    completed_ids: set[str] = field(default_factory=set)
    session_completed_ids: set[str] = field(default_factory=set)
    user_model: Any = field(default_factory=dict)
    topics_of_interest: list[str] = field(default_factory=list)

    def mark_completed(self, dialog_id: str) -> None:
        """Record a dialog as completed in both cumulative and in-session history.

        Called by the resolver's caller (typically ``SessionManager``) after each
        dialog finishes running, so that subsequent ``resolve()`` calls see
        up-to-date eligibility state.

        Parameters
        ----------
        dialog_id : str
            ID of the dialog that just finished.
        """
        self.completed_ids.add(dialog_id)
        self.session_completed_ids.add(dialog_id)


# ── Base ──────────────────────────────────────────────────────────────────────

class AgendaItem(ABC):
    """Base class for all agenda items.

    Each concrete item resolves to zero or one dialog per call, given the
    current ``AgendaContext``.  Returning ``None`` signals that no dialog could
    be selected (e.g. ID not found, all candidates exhausted) and the resolver
    should move to the next item.
    """

    @abstractmethod
    def resolve(self, context: AgendaContext) -> "BaseDialog | None":
        """Select and return a dialog, or None if nothing can be resolved.

        Parameters
        ----------
        context : AgendaContext
            Current session state used to filter and rank candidates.

        Returns
        -------
        BaseDialog | None
            The selected dialog, or None if the item cannot be resolved.
        """


# ── DialogRef ─────────────────────────────────────────────────────────────────

class DialogRef(BaseModel, AgendaItem):
    """Direct reference to a dialog by exact ID.

    Backward-compatible with plain string agenda entries — ``coerce_agenda_item``
    wraps any string in a ``DialogRef`` automatically.

    JSON forms (both produce the same result)::

        "greeting"
        {"type": "dialog_ref", "id": "greeting"}
    """

    type: Literal["dialog_ref"] = "dialog_ref"
    id: str

    def resolve(self, context: AgendaContext) -> "BaseDialog | None":
        """Look up the dialog by ID in the registry.

        Logs a warning and returns None if the ID is not found so the resolver
        can continue with the next item rather than crashing.
        """
        dialog = context.registry.get_by_id(self.id)
        if dialog is None:
            logger.warning("DialogRef: id %r not found in registry — skipping.", self.id)
        return dialog


# ── Helpers ───────────────────────────────────────────────────────────────────

def _apply_overrides(
    dialog: LLMDialog,
    max_turns: int | None,
    duration: float | None,
) -> LLMDialog:
    """Return a shallow copy of *dialog* with optional field overrides applied.

    The registry entry is never mutated — callers always receive a fresh copy.

    Parameters
    ----------
    dialog : LLMDialog
        Original dialog from the registry.
    max_turns : int | None
        Override ``LLMDialog.max_turns`` when not None.
    duration : float | None
        Override ``LLMDialog.duration`` when not None.

    Returns
    -------
    LLMDialog
        New instance with the requested fields replaced.
    """
    new_dialog = copy.copy(dialog)
    if max_turns is not None:
        new_dialog.max_turns = max_turns
    if duration is not None:
        new_dialog.duration = duration
    return new_dialog


# ── NarrativeSlot ─────────────────────────────────────────────────────────────

class NarrativeSlot(BaseModel, AgendaItem):
    """Advance a narrative thread by resolving its next eligible dialog.

    Selects the lowest-``position`` eligible ``NarrativeDialog`` in *thread*,
    with a random tiebreak among dialogs sharing the minimum position.

    The resolver calls ``resolve()`` once per run, updates
    ``AgendaContext.completed_ids``, then re-queues this item according to
    ``bounds``.  ``NarrativeSlot`` itself always resolves a single step.

    Attributes
    ----------
    thread : str
        Narrative thread name; must match ``NarrativeDialog.thread``.
    bounds : SlotBounds
        Controls how many times the resolver re-queues this item.
        Default: exactly once.
    eligibility_policy : EligibilityPolicy | None
        Per-slot override.  ``None`` falls back to
        ``NarrativeDialog.DEFAULT_ELIGIBILITY``.
    """

    type: Literal["narrative_slot"] = "narrative_slot"
    thread: str
    bounds: SlotBounds = SlotBounds()
    # Excluded from serialisation — EligibilityPolicy is a plain Python object,
    # not a Pydantic model.  Set programmatically only.
    eligibility_policy: EligibilityPolicy | None = Field(default=None, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def resolve(self, context: AgendaContext) -> "BaseDialog | None":
        """Return the next eligible NarrativeDialog in the thread, or None.

        Parameters
        ----------
        context : AgendaContext
            Current session state used for eligibility filtering.

        Returns
        -------
        BaseDialog | None
            Lowest-position eligible dialog, randomly chosen among ties.
            ``None`` (with a warning) if no eligible candidate exists.
        """
        candidates = context.registry.get_by_attr("thread", self.thread)
        policy = self.eligibility_policy or NarrativeDialog.DEFAULT_ELIGIBILITY
        eligible = [d for d in candidates if policy.is_eligible(d, context)]
        if not eligible:
            logger.warning("NarrativeSlot: no eligible dialog in thread '%s'", self.thread)
            return None
        # Lowest position wins; random tiebreak among dialogs sharing the minimum
        min_pos = min(d.position for d in eligible)
        return random.choice([d for d in eligible if d.position == min_pos])


# ── ChitchatSlot ──────────────────────────────────────────────────────────────

class ChitchatSlot(BaseModel, AgendaItem):
    """Select a chitchat dialog ranked by topic overlap with the user's interests.

    Candidates are all eligible ``ChitchatDialog`` instances.  They are first
    shuffled (random tiebreak), then sorted descending by the count of topics
    shared with ``AgendaContext.topics_of_interest``.

    Attributes
    ----------
    bounds : SlotBounds
        Controls how many times the resolver re-queues this item.
        Default: exactly once.
    topics_filter : list[str] | None
        When set, restricts candidates to dialogs containing at least one of
        these topics before interest-overlap scoring.
    eligibility_policy : EligibilityPolicy | None
        Per-slot override.  ``None`` falls back to
        ``ChitchatDialog.DEFAULT_ELIGIBILITY``.
    """

    type: Literal["chitchat_slot"] = "chitchat_slot"
    bounds: SlotBounds = SlotBounds()
    topics_filter: list[str] | None = None
    eligibility_policy: EligibilityPolicy | None = Field(default=None, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def resolve(self, context: AgendaContext) -> "BaseDialog | None":
        """Return the highest-interest-overlap eligible chitchat dialog, or None.

        Parameters
        ----------
        context : AgendaContext
            Current session state; ``topics_of_interest`` drives ranking.

        Returns
        -------
        BaseDialog | None
            Top-ranked eligible dialog after interest scoring.
            ``None`` (with a warning) if no eligible candidate exists.
        """
        candidates = context.registry.get_by_type(DialogType.CHITCHAT)
        policy = self.eligibility_policy or ChitchatDialog.DEFAULT_ELIGIBILITY
        eligible = [d for d in candidates if policy.is_eligible(d, context)]
        if self.topics_filter:
            eligible = [
                d for d in eligible
                if any(t in d.topics for t in self.topics_filter)
            ]
        if not eligible:
            logger.warning("ChitchatSlot: no eligible chitchat dialog found")
            return None
        # Shuffle first so equal-scoring candidates have a random tiebreak
        random.shuffle(eligible)
        # Primary rank: dialogs with more dependencies already met are more
        # contextually specific (they were authored to follow prior dialogs).
        # Secondary rank: topic overlap with user interests.
        eligible.sort(
            key=lambda d: (
                sum(1 for dep in d.dependencies if dep in context.completed_ids),
                len(set(d.topics) & set(context.topics_of_interest)),
            ),
            reverse=True,
        )
        return eligible[0]


# ── FunctionalSlot ────────────────────────────────────────────────────────────

class FunctionalSlot(BaseModel, AgendaItem):
    """Select a functional dialog by its declared role (greeting, farewell, …).

    ``FunctionalDialog.DEFAULT_ELIGIBILITY`` has no ``ExcludeIfSeenRule``, so
    functional dialogs re-run every session by default.  When multiple eligible
    candidates share the same ``functional_type``, one is chosen at random.

    Attributes
    ----------
    functional_type : str
        Role identifier; must match ``FunctionalDialog.functional_type``.
    bounds : SlotBounds
        Controls how many times the resolver re-queues this item.
        Default: exactly once.
    eligibility_policy : EligibilityPolicy | None
        Per-slot override.  ``None`` falls back to
        ``FunctionalDialog.DEFAULT_ELIGIBILITY``.
    """

    type: Literal["functional_slot"] = "functional_slot"
    functional_type: str
    bounds: SlotBounds = SlotBounds()
    eligibility_policy: EligibilityPolicy | None = Field(default=None, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def resolve(self, context: AgendaContext) -> "BaseDialog | None":
        """Return a random eligible FunctionalDialog for the given role, or None.

        Parameters
        ----------
        context : AgendaContext
            Current session state used for eligibility filtering.

        Returns
        -------
        BaseDialog | None
            Random eligible candidate, or ``None`` (with a warning) if none found.
        """
        candidates = context.registry.get_by_attr("functional_type", self.functional_type)
        policy = self.eligibility_policy or FunctionalDialog.DEFAULT_ELIGIBILITY
        eligible = [d for d in candidates if policy.is_eligible(d, context)]
        if not eligible:
            logger.warning(
                "FunctionalSlot: no eligible dialog with functional_type='%s'",
                self.functional_type,
            )
            return None
        return random.choice(eligible)


# ── LLMDialogRef ──────────────────────────────────────────────────────────────

class LLMDialogRef(BaseModel, AgendaItem):
    """Direct reference to a pre-authored LLMDialog by ID.

    Unlike the slot types, ``LLMDialogRef`` does *not* select from a pool — it
    pins to an exact dialog ID.  Optional ``max_turns`` and ``duration`` override
    the dialog's own settings for that run without mutating the registry entry.

    A missing or wrong-typed ID logs a warning and returns ``None`` so the
    session continues with the next agenda item rather than crashing.

    Attributes
    ----------
    id : str
        Registry ID of the target ``LLMDialog``.
    max_turns : int | None
        Per-run override for ``LLMDialog.max_turns``.
    duration : float | None
        Per-run override for ``LLMDialog.duration`` (seconds).
    """

    type: Literal["llm_dialog_ref"] = "llm_dialog_ref"
    id: str
    max_turns: int | None = None
    duration: float | None = None

    def resolve(self, context: AgendaContext) -> "BaseDialog | None":
        """Look up the LLMDialog by ID and apply any overrides.

        Parameters
        ----------
        context : AgendaContext
            Current session state; only the registry is used.

        Returns
        -------
        BaseDialog | None
            The (optionally overridden) LLMDialog, or ``None`` if the ID is not
            found or does not point to an LLMDialog.
        """
        dialog = context.registry.get_by_id(self.id)
        if dialog is None:
            logger.warning(
                "LLMDialogRef: dialog '%s' not found in registry — skipping agenda item",
                self.id,
            )
            return None
        if not isinstance(dialog, LLMDialog):
            logger.warning(
                "LLMDialogRef: dialog '%s' is not an LLMDialog (got %s) — skipping",
                self.id,
                type(dialog).__name__,
            )
            return None
        if self.max_turns is not None or self.duration is not None:
            return _apply_overrides(dialog, max_turns=self.max_turns, duration=self.duration)
        return dialog


# ── Discriminated union ───────────────────────────────────────────────────────

AnyAgendaItem = Annotated[
    Union[DialogRef, NarrativeSlot, ChitchatSlot, FunctionalSlot, LLMDialogRef],
    Field(discriminator="type"),
]


# ── Coercion helper ───────────────────────────────────────────────────────────

def coerce_agenda_item(item: "str | dict | AgendaItem") -> AgendaItem:
    """Normalise an agenda entry to a typed ``AgendaItem``.

    Accepts three forms:

    * ``str`` — wrapped in ``DialogRef(id=item)`` for backward compatibility.
    * ``dict`` — parsed as a Pydantic discriminated union (``AnyAgendaItem``).
    * ``AgendaItem`` — returned unchanged.

    Parameters
    ----------
    item : str | dict | AgendaItem
        Raw agenda entry from JSON or Python configuration.

    Returns
    -------
    AgendaItem
        Typed agenda item ready for resolution.

    Raises
    ------
    TypeError
        If ``item`` is none of the accepted types.
    pydantic.ValidationError
        If a dict cannot be parsed as a known agenda item type.
    """
    if isinstance(item, str):
        return DialogRef(id=item)
    if isinstance(item, dict):
        from pydantic import TypeAdapter
        _adapter: TypeAdapter[AnyAgendaItem] = TypeAdapter(AnyAgendaItem)
        return _adapter.validate_python(item)
    if isinstance(item, AgendaItem):
        return item
    raise TypeError(f"Cannot coerce {type(item)!r} to AgendaItem")
