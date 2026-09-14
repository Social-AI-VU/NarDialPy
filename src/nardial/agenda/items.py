import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from nardial.agenda.slot_bounds import SlotBounds
from nardial.eligibility import EligibilityPolicy
from nardial.mini_dialogs import DialogType

if TYPE_CHECKING:
    from nardial.dialog_registry import DialogRegistry
    from nardial.mini_dialogs import MiniDialog

logger = logging.getLogger(__name__)


@dataclass
class AgendaContext:
    """Mutable state agenda items resolve against.

    Exposes the same attribute names as `eligibility.EligibilityContext`
    (`registry`, `completed_ids`, `session_completed_ids`, `user_model`) so
    it can be passed anywhere an `EligibilityContext` is expected, plus the
    fields agenda items themselves need (`topics_of_interest`,
    `mark_completed`).
    """
    registry: Optional["DialogRegistry"] = None
    completed_ids: List[str] = field(default_factory=list)
    session_completed_ids: List[str] = field(default_factory=list)
    user_model: Dict[str, Any] = field(default_factory=dict)
    topics_of_interest: List[str] = field(default_factory=list)

    def mark_completed(self, dialog_id: str) -> None:
        if dialog_id not in self.completed_ids:
            self.completed_ids.append(dialog_id)
        if dialog_id not in self.session_completed_ids:
            self.session_completed_ids.append(dialog_id)


def _is_eligible(dialog: "MiniDialog", context: AgendaContext, policy: Optional[EligibilityPolicy]) -> bool:
    """Evaluate `dialog` against `policy`, falling back to its class's `DEFAULT_ELIGIBILITY`."""
    effective_policy = policy or EligibilityPolicy(list(getattr(type(dialog), "DEFAULT_ELIGIBILITY", [])))
    return effective_policy.is_eligible(dialog, context)


class AgendaItem(ABC):
    """A single entry on a session agenda.

    Resolves against an `AgendaContext` to a concrete dialog to run next,
    or `None` if nothing currently qualifies.
    """

    @abstractmethod
    def resolve(self, context: AgendaContext) -> Optional["MiniDialog"]:
        ...


class DialogRef(AgendaItem):
    """Pins a specific dialog by id. No `bounds` attribute: always resolves at most once."""

    def __init__(self, id: str):
        self.id = id

    def resolve(self, context: AgendaContext) -> Optional["MiniDialog"]:
        dialog = context.registry.get_by_id(self.id) if context.registry else None
        if dialog is None:
            logger.warning("DialogRef: no dialog found for id %r", self.id)
        return dialog


class NarrativeSlot(AgendaItem):
    """Resolves to the lowest-position eligible dialog in `thread`.

    Ties (multiple eligible dialogs at the same lowest position) are broken
    randomly.
    """

    def __init__(self, thread: str, bounds: Optional[SlotBounds] = None,
                 eligibility_policy: Optional[EligibilityPolicy] = None):
        self.thread = thread
        self.bounds = bounds or SlotBounds()
        self.eligibility_policy = eligibility_policy

    def resolve(self, context: AgendaContext) -> Optional["MiniDialog"]:
        if context.registry is None:
            logger.warning("NarrativeSlot(thread=%r): no registry on context", self.thread)
            return None

        candidates = context.registry.get_by_attr("thread", self.thread)
        eligible = [d for d in candidates if _is_eligible(d, context, self.eligibility_policy)]
        positioned = [d for d in eligible if getattr(d, "position", None) is not None]
        if not positioned:
            logger.warning("NarrativeSlot(thread=%r): no eligible candidates", self.thread)
            return None

        min_position = min(d.position for d in positioned)
        lowest = [d for d in positioned if d.position == min_position]
        return random.choice(lowest)


class ChitchatSlot(AgendaItem):
    """Resolves to the eligible `ChitchatDialog` with the most topic overlap with `context.topics_of_interest`.

    Ties are broken randomly (shuffle before the stable sort by overlap
    count). `topics_filter`, when given, restricts candidates to dialogs
    that share at least one topic with it before ranking.
    """

    def __init__(self, bounds: Optional[SlotBounds] = None, topics_filter: Optional[List[str]] = None,
                 eligibility_policy: Optional[EligibilityPolicy] = None):
        self.bounds = bounds or SlotBounds()
        self.topics_filter = list(topics_filter) if topics_filter else None
        self.eligibility_policy = eligibility_policy

    def resolve(self, context: AgendaContext) -> Optional["MiniDialog"]:
        if context.registry is None:
            logger.warning("ChitchatSlot: no registry on context")
            return None

        candidates = context.registry.get_by_type(DialogType.CHITCHAT)
        if self.topics_filter:
            filter_set = {str(t).lower() for t in self.topics_filter}
            candidates = [
                d for d in candidates
                if filter_set & {str(t).lower() for t in getattr(d, "topics", [])}
            ]

        eligible = [d for d in candidates if _is_eligible(d, context, self.eligibility_policy)]
        if not eligible:
            logger.warning("ChitchatSlot: no eligible candidates")
            return None

        random.shuffle(eligible)
        interests = {str(t).lower() for t in (context.topics_of_interest or [])}

        def overlap(dialog: "MiniDialog") -> int:
            topics = {str(t).lower() for t in getattr(dialog, "topics", [])}
            return len(topics & interests)

        eligible.sort(key=overlap, reverse=True)
        return eligible[0]


def coerce_agenda_item(item: Union[str, Dict[str, Any], AgendaItem]) -> AgendaItem:
    """Coerce a raw agenda entry (string id, dict, or AgendaItem) into an AgendaItem.

    Mirrors `DialogFactory.from_json()`'s manual type-string dispatch rather
    than a Pydantic discriminated union. Only `"dialog_ref"` is registered
    here; later agenda item types register their own branch.
    """
    if isinstance(item, AgendaItem):
        return item
    if isinstance(item, str):
        return DialogRef(id=item)
    if isinstance(item, dict):
        item_type = item.get("type")
        if item_type == "dialog_ref":
            return DialogRef(id=item["id"])
        if item_type == "narrative_slot":
            return NarrativeSlot(thread=item["thread"], bounds=SlotBounds.from_dict(item.get("bounds")))
        if item_type == "chitchat_slot":
            return ChitchatSlot(
                bounds=SlotBounds.from_dict(item.get("bounds")),
                topics_filter=item.get("topics_filter"),
            )
        raise ValueError(f"Unknown agenda item type: {item_type!r}")
    raise ValueError(f"Unsupported agenda item: {item!r}")
