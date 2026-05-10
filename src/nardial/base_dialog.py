from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nardial.conversation_agent import ConversationAgent
    from nardial.mini_dialogs import RunContext


class BaseDialog(ABC):
    """Abstract base for all dialog types in NarDialPy.

    Defines the minimal interface required by ``SessionManager``: dialog
    identity, dependency declarations, and the ``run()`` execution hook.

    Concrete subclasses:

    - ``MiniDialog`` — executes a declarative sequence of typed moves.
    - ``LLMDialog`` — drives a free-form multi-turn LLM conversation without
      a scripted move list.

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

    @abstractmethod
    def run(self, agent: ConversationAgent, context: RunContext) -> None:
        """Execute this dialog using the given agent and run context.

        Parameters
        ----------
        agent : ConversationAgent
            Capability provider for speech, listening, and LLM calls.
        context : RunContext
            Mutable conversational state accumulating during this session run.
        """
