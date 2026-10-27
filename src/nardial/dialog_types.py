"""Registry mapping dialog JSON ``"type"`` strings to `MiniDialog` subclasses.

`DialogFactory` looks dialog classes up here instead of hard-coding the
built-in types, so users can add their own dialog types by subclassing an
existing one and registering it::

    @register_dialog_type("evening_chitchat")
    class EveningChitchat(ChitchatDialog):
        DEFAULT_ELIGIBILITY = ChitchatDialog.DEFAULT_ELIGIBILITY + [MyRule()]

A subclass inherits its parent's `validate_doc()`/`from_doc()`/`to_doc()`
and `DIALOG_TYPE`, so agenda slots that select by `DIALOG_TYPE` (e.g.
`ChitchatSlot`) still pick it up. This module never imports
`mini_dialogs.py` at runtime, to avoid a cycle (the built-in classes
register themselves on import).
"""
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Type

if TYPE_CHECKING:
    from nardial.mini_dialogs import MiniDialog

_DIALOG_TYPES: Dict[str, Type["MiniDialog"]] = {}


def register_dialog_type(name: str) -> Callable[[Type["MiniDialog"]], Type["MiniDialog"]]:
    """Class decorator registering `cls` under the JSON type string `name`.

    Sets `cls.TYPE_NAME = name`. Re-registering the same class is a no-op;
    registering a different class under a taken name raises `ValueError`.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("dialog type name must be a non-empty string")

    def decorator(cls: Type["MiniDialog"]) -> Type["MiniDialog"]:
        existing = _DIALOG_TYPES.get(name)
        if existing is not None and existing is not cls:
            raise ValueError(f"dialog type {name!r} is already registered to {existing.__name__}")
        cls.TYPE_NAME = name
        _DIALOG_TYPES[name] = cls
        return cls

    return decorator


def get_dialog_type(name: str) -> Optional[Type["MiniDialog"]]:
    return _DIALOG_TYPES.get(name)


def dialog_type_names() -> List[str]:
    return list(_DIALOG_TYPES)
