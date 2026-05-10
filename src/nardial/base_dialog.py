from __future__ import annotations

from abc import ABC
from typing import Any


class BaseDialog(ABC):
    """Abstract base for all dialog types in NarDialPy.

    Defines the minimal interface required by the system: dialog identity and
    dependency declarations.  Execution is handled by
    :class:`~nardial.dialog_runtime.DialogRuntime`, which accepts any
    ``BaseDialog`` subclass and dispatches to the appropriate async handler.

    Concrete subclasses:

    - ``MiniDialog`` — holds a declarative sequence of typed moves.
    - ``LLMDialog`` — holds configuration for a free-form multi-turn LLM
      conversation without a scripted move list.

    Parameters
    ----------
    dialog_id : str
        Unique identifier for this dialog (e.g. ``"pineapple_on_pizza"``).
    dependencies : list of str, optional
        Dialog IDs that must be completed before this dialog can run.
    variable_dependencies : list of dict, optional
        User model variables that must be present before this dialog can run.
        Each entry is ``{"variable": str, "required": bool}``.
    """

    def __init__(self, dialog_id: str, dependencies: list[str] | None = None,
                 variable_dependencies: list[Any] | None = None) -> None:
        self.dialog_id = dialog_id
        self.dependencies: list[str] = dependencies or []
        self.variable_dependencies: list[Any] = variable_dependencies or []
