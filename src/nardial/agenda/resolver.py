from collections import deque
from time import monotonic
from typing import Any, Dict, Iterable, Iterator, Union

from nardial.agenda.items import AgendaContext, AgendaItem, coerce_agenda_item
from nardial.mini_dialogs import MiniDialog


def resolve_agenda(items: Iterable[Union[str, Dict[str, Any], AgendaItem]],
                    context: AgendaContext) -> Iterator[MiniDialog]:
    """Yield dialogs from `items` in order, respecting each item's `SlotBounds`.

    A deque-based generator. Items with no `bounds` attribute (`DialogRef`,
    `LLMDialogRef`) always resolve at most once. Items with `bounds` are
    re-queued (`appendleft`) until `count_max`/`duration_max` is hit (hard
    ceilings, checked first) or both the `count_min`/`duration_min` floors
    are met. Per-item run-count/start-time live in local dicts keyed by
    `id(item)` rather than on the `AgendaItem` instances themselves, which
    keeps those instances effectively immutable. A `None` resolution is
    skipped and never re-queued, regardless of bounds.

    The caller is expected to call `context.mark_completed(dialog.dialog_id)`
    between yields (e.g. after actually running the dialog) so a re-queued
    item sees updated eligibility on its next resolve.
    """
    queue = deque(coerce_agenda_item(item) for item in items)
    run_counts: Dict[int, int] = {}
    start_times: Dict[int, float] = {}

    while queue:
        item = queue.popleft()
        dialog = item.resolve(context)
        if dialog is None:
            continue

        bounds = getattr(item, "bounds", None)
        if bounds is None:
            yield dialog
            continue

        key = id(item)
        if key not in start_times:
            start_times[key] = monotonic()
        run_counts[key] = run_counts.get(key, 0) + 1

        yield dialog

        count = run_counts[key]
        elapsed = monotonic() - start_times[key]

        count_max_reached = bounds.count_max is not None and count >= bounds.count_max
        duration_max_reached = bounds.duration_max is not None and elapsed >= bounds.duration_max
        if count_max_reached or duration_max_reached:
            continue

        count_min_met = bounds.count_min is None or count >= bounds.count_min
        duration_min_met = bounds.duration_min is None or elapsed >= bounds.duration_min
        if not (count_min_met and duration_min_met):
            queue.appendleft(item)
