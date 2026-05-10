"""Queue-based incremental agenda resolver.

``resolve_agenda()`` is a generator that drives the SessionManager loop.  It
processes a :class:`~collections.deque` of :class:`AgendaItem` objects one step
at a time: resolve → yield → caller runs dialog and calls
``context.mark_completed()`` → advance.

This incremental pattern is what allows multi-resolve slots (e.g.
``NarrativeSlot(bounds=SlotBounds(count_min=2))``) to select their next step
with fully up-to-date eligibility state after each dialog completes.

Typical usage::

    context = AgendaContext(registry=registry, completed_ids=seen_ids)
    for dialog in resolve_agenda(agenda_items, context):
        dialog.run(agent, run_context)
        context.mark_completed(dialog.dialog_id)
"""

from __future__ import annotations

import collections
import logging
from time import monotonic
from typing import TYPE_CHECKING, Generator

from nardial.agenda.items import AgendaContext, AgendaItem, to_agenda_item
from nardial.agenda.slot_bounds import SlotBounds

if TYPE_CHECKING:
    from nardial.mini_dialogs import MiniDialog

logger = logging.getLogger(__name__)


# ── Per-slot resolver state ───────────────────────────────────────────────────

class SlotState:
    """Tracks per-item resolution progress for multi-resolve slots.

    Not part of the public API — used only inside ``resolve_agenda``.

    Attributes
    ----------
    item : AgendaItem
        The agenda item being resolved.
    dialogs_run : int
        Number of dialogs this slot has successfully resolved so far.
    started_at : float | None
        ``time.monotonic()`` timestamp of the first successful resolution,
        or ``None`` if the slot has not yet produced a dialog.
    """

    __slots__ = ("item", "dialogs_run", "started_at")

    def __init__(self, item: AgendaItem) -> None:
        self.item = item
        self.dialogs_run: int = 0
        self.started_at: float | None = None


# ── Bounds helpers ────────────────────────────────────────────────────────────

def _elapsed(state: SlotState) -> float:
    """Return seconds since the slot first resolved, or 0.0 if not yet started."""
    return 0.0 if state.started_at is None else (monotonic() - state.started_at)


def _should_requeue(bounds: SlotBounds, dialogs_run: int, elapsed: float) -> bool:
    """Return True if the slot should be placed back at the front of the deque.

    Decision order (highest precedence first):

    1. ``duration_max`` exceeded → False (hard ceiling, overrides everything).
    2. ``dialogs_run < count_min`` → True (minimum count not yet satisfied).
    3. ``elapsed < duration_min`` → True (minimum time window not yet filled).
    4. ``count_max`` not yet reached (or unlimited) → True (may run more).
    5. Otherwise → False (all bounds satisfied, retire the slot).

    Parameters
    ----------
    bounds : SlotBounds
        The slot's cardinality/duration constraints.
    dialogs_run : int
        How many dialogs the slot has produced so far.
    elapsed : float
        Seconds since the slot first resolved.
    """
    # 1. Hard time ceiling.
    if bounds.duration_max is not None and elapsed >= bounds.duration_max:
        return False
    # 2. Count minimum not yet satisfied.
    if dialogs_run < bounds.count_min:
        return True
    # 3. Duration minimum not yet filled.
    if bounds.duration_min is not None and elapsed < bounds.duration_min:
        return True
    # 4. Count maximum not yet reached (or unlimited).
    if bounds.count_max is None or dialogs_run < bounds.count_max:
        return True
    return False


# ── Resolver ─────────────────────────────────────────────────────────────────

def resolve_agenda(
    items: "list[str | dict | AgendaItem]",
    context: AgendaContext,
) -> "Generator[MiniDialog, None, None]":
    """Incrementally resolve an agenda, yielding one dialog at a time.

    Each yielded dialog should be run by the caller, followed by a call to
    ``context.mark_completed(dialog.dialog_id)`` before the generator advances.
    The generator only resumes on the next ``next()`` call, so
    ``AgendaContext`` is always current when the next item is resolved.

    Multi-resolve slots (items carrying a ``bounds: SlotBounds`` attribute) are
    re-queued at the front of the deque until their bounds are satisfied or the
    candidate pool is exhausted.  A warning is logged whenever a slot retires
    without having met its ``count_min``.

    Parameters
    ----------
    items : list[str | dict | AgendaItem]
        Flat agenda.  Strings and dicts are coerced via ``to_agenda_item``.
    context : AgendaContext
        Mutable session state.  The caller updates it via ``mark_completed``
        after each dialog run.

    Yields
    ------
    MiniDialog
        The next dialog to run.
    """
    queue: collections.deque[SlotState] = collections.deque(
        SlotState(to_agenda_item(i)) for i in items
    )

    while queue:
        state = queue.popleft()
        item = state.item
        bounds: SlotBounds | None = getattr(item, "bounds", None)

        # Hard time ceiling — skip if duration_max has elapsed since the slot
        # was last re-queued (time passes while other dialogs run).
        if bounds is not None and state.started_at is not None:
            if bounds.duration_max is not None and _elapsed(state) >= bounds.duration_max:
                if state.dialogs_run < bounds.count_min:
                    logger.warning(
                        "%s: duration_max=%.1fs exceeded after %d dialog(s)"
                        " (count_min=%d) — retiring slot",
                        type(item).__name__,
                        bounds.duration_max,
                        state.dialogs_run,
                        bounds.count_min,
                    )
                continue

        dialog = item.resolve(context)

        if dialog is None:
            # Pool exhausted or no eligible candidate; warn if minimum unmet.
            if bounds is not None and state.dialogs_run < bounds.count_min:
                logger.warning(
                    "%s: pool exhausted after %d dialog(s) but count_min=%d"
                    " — retiring slot",
                    type(item).__name__,
                    state.dialogs_run,
                    bounds.count_min,
                )
            continue

        # Record when this slot first produced a dialog (for duration tracking).
        if state.started_at is None:
            state.started_at = monotonic()

        yield dialog
        # Caller: dialog.run(agent, run_context); context.mark_completed(dialog.dialog_id)

        state.dialogs_run += 1

        if bounds is not None and _should_requeue(bounds, state.dialogs_run, _elapsed(state)):
            queue.appendleft(state)
