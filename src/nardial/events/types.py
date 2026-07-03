"""Core event types for the NarDialPy event system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

EVENT_INTERACTION_PAUSE = "interaction_pause"
EVENT_INTERACTION_RESUME = "interaction_resume"


class InterruptLevel(str, Enum):
    """Granularity at which an event can interrupt the dialog session.

    String-valued so that JSON round-trips work naturally: designers can write
    ``"BETWEEN_DIALOGS"`` in a session plan file and Pydantic validates it
    without any coercion layer.
    """

    BETWEEN_DIALOGS = "BETWEEN_DIALOGS"   # handled only between full dialog executions
    BETWEEN_MOVES   = "BETWEEN_MOVES"     # handled between individual moves within a dialog
    IMMEDIATE       = "IMMEDIATE"         # cancels the running dialog task mid-execution


class ResumePolicy(str, Enum):
    """What to do with the interrupted dialog after its handler finishes.

    String-valued for the same JSON-friendliness reason as :class:`InterruptLevel`.
    """

    DISCARD = "DISCARD"   # interrupted dialog is dropped; next agenda item runs
    PAUSE   = "PAUSE"     # interrupted dialog is checkpointed and resumes after the handler


_seq_counter = 0
_seq_lock = __import__("threading").Lock()


def _next_seq() -> int:
    global _seq_counter
    with _seq_lock:
        _seq_counter += 1
        return _seq_counter


@dataclass(order=True)
class Event:
    """A discrete occurrence emitted by an :class:`~nardial.events.source.EventSource`.

    The dataclass is ordered so that :class:`~nardial.events.bus.EventBus` can
    store events in an ``asyncio.PriorityQueue``.  Only ``priority`` and ``seq``
    participate in ordering — all other fields are excluded from comparison via
    ``compare=False``.

    Lower ``priority`` values are processed first.  ``seq`` is a monotonically
    increasing tiebreaker assigned at construction time.
    """

    priority: int                                       # lower = higher priority
    type:     str      = field(compare=False)           # e.g. "button_press"
    source:   str      = field(compare=False)           # emitting source_id
    data:     Any      = field(compare=False, default=None)   # arbitrary payload
    interrupt_level: InterruptLevel = field(
        compare=False, default=InterruptLevel.BETWEEN_DIALOGS
    )
    resume_policy: ResumePolicy = field(
        compare=False, default=ResumePolicy.DISCARD
    )
    handler_dialog_id: str | None = field(compare=False, default=None)
    seq: int = field(compare=True, default_factory=_next_seq)
