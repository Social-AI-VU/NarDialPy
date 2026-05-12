"""SlotBounds — configurable count and duration bounds for multi-resolve agenda slots.

Used by ``NarrativeSlot``, ``ChitchatSlot``, and ``FunctionalSlot`` to control how
many times the resolver re-queues an item.  The resolver (#102) is responsible for
reading these bounds between iterations and deciding when to stop.
"""

from __future__ import annotations

from pydantic import BaseModel


class SlotBounds(BaseModel):
    """Min/max count and duration bounds controlling how many times a slot resolves.

    Default ``SlotBounds()`` = resolve exactly once, no time constraints.

    Attributes
    ----------
    count_min : int
        Resolve at least this many times before the slot may be retired.  Default 1.
    count_max : int | None
        Hard upper limit on resolutions.  ``None`` means no upper limit — the slot
        continues until the pool is exhausted or a duration ceiling is hit.
        Default 1, which together with ``count_min=1`` means exactly once.
    duration_min : float | None
        Keep resolving until at least this many seconds have elapsed since the slot
        first resolved.  ``None`` means no minimum time requirement.
    duration_max : float | None
        Hard time ceiling.  The resolver stops the slot once this many seconds have
        elapsed, even if ``count_min`` has not yet been satisfied.  ``None`` means
        no time ceiling.

    Notes
    -----
    Resolver contract (enforced in ``resolve_agenda()``, issue #102):

    * **Must continue** if ``dialogs_run < count_min`` AND ``duration_max`` not exceeded.
    * **May continue** if ``(count_max is None OR dialogs_run < count_max)``
      AND ``duration_max`` not exceeded.
    * **Stops on**: ``duration_max`` exceeded (hard ceiling), ``count_max`` reached,
      or pool exhausted (``resolve()`` returns ``None``).
    * If ``duration_max`` fires before ``count_min`` is satisfied, the resolver logs
      a warning and moves on — the session is not failed.

    Examples
    --------
    Exactly once (default)::

        SlotBounds()

    Two to four resolutions::

        SlotBounds(count_min=2, count_max=4)

    At least once, stop after 3 minutes::

        SlotBounds(count_max=None, duration_max=180)

    At least three, no upper limit::

        SlotBounds(count_min=3, count_max=None)

    Two-to-five-minute window::

        SlotBounds(count_min=1, duration_min=120, duration_max=300)
    """

    count_min: int = 1
    count_max: int | None = 1
    duration_min: float | None = None
    duration_max: float | None = None
