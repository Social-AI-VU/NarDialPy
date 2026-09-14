import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from nardial.mini_dialogs import MiniDialog

logger = logging.getLogger(__name__)


class DialogRegistry:
    """Indexed lookup over a set of MiniDialog objects.

    Built once via `DialogRegistry.build()`, then queried by agenda items
    instead of linear-scanning the raw dialog list. Each dialog class
    declares its own `DIALOG_TYPE` / `INDEX_ATTRS` class attributes, so the
    registry never needs an `isinstance` chain against concrete dialog
    classes.
    """

    def __init__(self) -> None:
        self.by_id: Dict[str, MiniDialog] = {}
        self.by_type: Dict[Any, List[MiniDialog]] = defaultdict(list)
        self.indexes: Dict[str, Dict[Any, List[MiniDialog]]] = defaultdict(lambda: defaultdict(list))

    @classmethod
    def build(cls, dialogs: List[MiniDialog]) -> "DialogRegistry":
        registry = cls()

        for dialog in dialogs:
            dialog_id = getattr(dialog, "dialog_id", None)
            if not dialog_id:
                logger.warning("Skipping dialog with no dialog_id: %r", dialog)
                continue
            if dialog_id in registry.by_id:
                logger.warning("Duplicate dialog_id %r; keeping the first, skipping the rest", dialog_id)
                continue

            registry.by_id[dialog_id] = dialog

            dialog_type = getattr(dialog, "DIALOG_TYPE", None)
            if dialog_type is not None:
                registry.by_type[dialog_type].append(dialog)

            for attr in getattr(dialog, "INDEX_ATTRS", []):
                value = getattr(dialog, attr, None)
                if value is None:
                    continue
                if isinstance(value, (list, tuple, set)):
                    for element in value:
                        registry.indexes[attr][element].append(dialog)
                else:
                    registry.indexes[attr][value].append(dialog)

        return registry

    def get_by_id(self, dialog_id: str) -> Optional[MiniDialog]:
        return self.by_id.get(dialog_id)

    def get_by_type(self, dialog_type: Any) -> List[MiniDialog]:
        return list(self.by_type.get(dialog_type, []))

    def get_by_attr(self, attr: str, value: Any) -> List[MiniDialog]:
        return list(self.indexes.get(attr, {}).get(value, []))
