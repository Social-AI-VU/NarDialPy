"""Indexed dialog pool — replaces linear isinstance scans in dialog selection.

Each dialog class declares ``INDEX_ATTRS`` listing the attribute names to index.
The registry reads these generically, so no changes here are needed when new
dialog types are added.  List-valued attributes (e.g. ``ChitchatDialog.topics``)
are expanded element-by-element so ``get_by_attr("topics", "pizza")`` returns
every dialog whose topics list contains "pizza".
"""

import logging
from collections import defaultdict
from typing import Any

from nardial.mini_dialogs import MiniDialog
from nardial.mini_dialogs import DialogType

logger = logging.getLogger(__name__)


class DialogRegistry:
    """Typed, indexed pool of dialogs built once at session start.

    Attributes
    ----------
    by_id : dict[str, MiniDialog]
        Fast lookup by ``dialog_id``.
    by_type : dict[DialogType, list[MiniDialog]]
        All dialogs of a given type.
    indexes : dict[str, dict[str, list[MiniDialog]]]
        Attribute-value indexes declared via ``INDEX_ATTRS`` on each class.
        Outer key: attribute name.  Inner key: attribute value (str).
    """

    def __init__(
        self,
        by_id: dict[str, MiniDialog],
        by_type: dict[DialogType, list[MiniDialog]],
        indexes: dict[str, dict[str, list[MiniDialog]]],
    ) -> None:
        self.by_id = by_id
        self.by_type = by_type
        self.indexes = indexes

    # ── factory ──────────────────────────────────────────────────────────────

    @classmethod
    def build(cls, dialogs: list[MiniDialog]) -> "DialogRegistry":
        """Build the registry from a flat list of dialog objects.

        Reads ``INDEX_ATTRS`` from each dialog's class generically.  List-valued
        attributes are expanded so every element becomes an individual index key.

        Parameters
        ----------
        dialogs : list[MiniDialog]
            All loaded dialog objects.

        Returns
        -------
        DialogRegistry
            Fully populated registry.
        """
        by_id: dict[str, MiniDialog] = {}
        by_type: dict[DialogType, list[MiniDialog]] = defaultdict(list)
        indexes: dict[str, dict[str, list[MiniDialog]]] = defaultdict(lambda: defaultdict(list))

        for dialog in dialogs:
            # Index by ID — warn and skip on collision.
            did = dialog.dialog_id
            if did in by_id:
                logger.warning("Duplicate dialog_id %r — keeping first, skipping second.", did)
                continue
            by_id[did] = dialog

            # Index by type if the dialog carries a DialogType.
            dialog_type = getattr(dialog, "dialog_type", None)
            if dialog_type is not None:
                by_type[dialog_type].append(dialog)

            # Index by class-declared INDEX_ATTRS.
            for attr in getattr(type(dialog), "INDEX_ATTRS", []):
                value = getattr(dialog, attr, None)
                if value is None:
                    continue
                # Expand list-valued attrs element-by-element.
                if isinstance(value, list):
                    for element in value:
                        indexes[attr][str(element)].append(dialog)
                else:
                    indexes[attr][str(value)].append(dialog)

        return cls(
            by_id=dict(by_id),
            by_type=dict(by_type),
            indexes={k: dict(v) for k, v in indexes.items()},
        )

    # ── queries ───────────────────────────────────────────────────────────────

    def get_by_id(self, dialog_id: str) -> MiniDialog | None:
        """Return the dialog with the given ID, or None if not found."""
        return self.by_id.get(dialog_id)

    def get_by_type(self, dialog_type: DialogType) -> list[MiniDialog]:
        """Return all dialogs of the given type (empty list if none)."""
        return list(self.by_type.get(dialog_type, []))

    def get_by_attr(self, attr: str, value: Any) -> list[MiniDialog]:
        """Return dialogs indexed under the given attribute/value pair.

        Parameters
        ----------
        attr : str
            Attribute name declared in a class's ``INDEX_ATTRS``.
        value : Any
            The value to look up; converted to ``str`` for the key comparison.

        Returns
        -------
        list[MiniDialog]
            Matching dialogs, or an empty list if none.
        """
        return list(self.indexes.get(attr, {}).get(str(value), []))

    def __len__(self) -> int:
        return len(self.by_id)

    def __repr__(self) -> str:
        return f"DialogRegistry({len(self)} dialogs)"
