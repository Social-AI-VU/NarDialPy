"""Agenda item types and the shared context passed to every resolve() call.

New item types (NarrativeStep, ChitchatSlot, etc.) are added here as later
issues implement them.  Only add the Pydantic type literal to ``AnyAgendaItem``
once the class is defined — do not create placeholder entries.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

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


# ── Discriminated union (extended by later issues) ────────────────────────────

AnyAgendaItem = Annotated[
    Union[DialogRef],
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
