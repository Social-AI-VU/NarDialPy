"""Pure data containers for all dialog types.

All dialog classes (``ScriptedMiniDialog``, ``LLMMiniDialog``, and their
concrete subclasses) carry no execution logic — they are pure data: fields,
class-level index declarations, and default eligibility policies.  All
execution is handled by :class:`~nardial.dialog_runtime.DialogRuntime`.

Re-exports for backward compatibility with existing imports:
- ``RunContext``, ``DialogType``, ``MAX_LLM_TURNS``, ``extract_open_value``,
  ``_run_llm_exchange`` are still importable from this module (they live in
  ``dialog_runtime``).
"""

from __future__ import annotations

from abc import ABC
from enum import Enum
from typing import Any

from nardial.dialog_runtime import (
    MAX_LLM_TURNS,
    DialogType,
    RunContext,
    _run_llm_exchange,
    extract_open_value,
)
from nardial.eligibility import (
    DepsMetRule,
    EligibilityPolicy,
    ExcludeIfSeenRule,
    NarrativeOrderingRule,
    VariableDepsMetRule,
)
from nardial.moves import AnyMove


class MiniDialog(ABC):
    """Abstract base for all dialog types in NarDialPy.

    Defines the minimal interface required by the system: dialog identity and
    dependency declarations.  Execution is handled by
    :class:`~nardial.dialog_runtime.DialogRuntime`, which accepts any
    ``MiniDialog`` subclass and dispatches to the appropriate async handler.

    Concrete subclasses:

    - ``ScriptedMiniDialog`` — holds a declarative sequence of typed moves.
    - ``LLMMiniDialog`` — holds configuration for a free-form multi-turn LLM
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


class ScriptedMiniDialog(MiniDialog):
    """Pure-data scripted dialog: holds a fixed sequence of typed moves.

    Execution is delegated to :class:`~nardial.dialog_runtime.DialogRuntime`.

    Parameters
    ----------
    dialog_id : str
        Unique identifier (e.g. ``'pineapple_on_pizza'``).
    moves : list of AnyMove
        Typed move objects representing the dialog steps in order.
    dependencies : list of str, optional
        Dialog IDs that must be completed before this dialog can run.
    variable_dependencies : list of dict, optional
        User model variables required before this dialog can run.
    """

    # Fallback policy for direct ScriptedMiniDialog instantiation (e.g. in tests).
    DEFAULT_ELIGIBILITY = EligibilityPolicy([ExcludeIfSeenRule(), DepsMetRule(), VariableDepsMetRule()])

    def __init__(self, dialog_id: str, moves: list[AnyMove], dependencies=None,
                 variable_dependencies=None):
        super().__init__(dialog_id, dependencies, variable_dependencies)
        self.moves = moves

    @staticmethod
    def add_interest(topics_of_interest: list, topic: Any) -> None:
        """Append ``topic`` to ``topics_of_interest`` if not already present (case-insensitive)."""
        if topics_of_interest is None or not topic:
            return
        t = str(topic).strip()
        if not t:
            return
        low = t.lower()
        if all(low != str(x).lower() for x in topics_of_interest):
            topics_of_interest.append(t)


class FunctionalLabel(Enum):
    """Label for functional dialogs that serve a specific social or structural role.

    Values may be extended in the future to cover roles beyond greeting and farewell.
    """

    GREETING = "greeting"
    FAREWELL = "farewell"


class FunctionalDialog(ScriptedMiniDialog):
    # Indexed by the string value of functional_type (e.g. "greeting", "farewell").
    INDEX_ATTRS: list[str] = ["functional_type"]
    # No ExcludeIfSeenRule — greetings and farewells re-run at the start of every session.
    DEFAULT_ELIGIBILITY = EligibilityPolicy([DepsMetRule()])
    dialog_type: DialogType = DialogType.FUNCTIONAL

    def __init__(self, dialog_id, moves, functional_type, dependencies=None):
        # Functional dialogs are utility blocks such as greeting and farewell.
        super().__init__(dialog_id, moves, dependencies)
        # Coerce string values to the enum so comparisons work regardless of the caller's source.
        self.type = FunctionalLabel(functional_type) if isinstance(functional_type, str) else functional_type

    @property
    def functional_type(self) -> str:
        """String value of the functional label, used as the registry index key."""
        return self.type.value

    def is_greeting_dialog(self):
        return self.type == FunctionalLabel.GREETING

    def is_farewell_dialog(self):
        return self.type == FunctionalLabel.FAREWELL


class NarrativeDialog(ScriptedMiniDialog):
    INDEX_ATTRS: list[str] = ["thread"]
    DEFAULT_ELIGIBILITY = EligibilityPolicy([ExcludeIfSeenRule(), DepsMetRule(), VariableDepsMetRule(), NarrativeOrderingRule()])
    dialog_type: DialogType = DialogType.NARRATIVE

    def __init__(self, dialog_id, moves, thread, position, dependencies=None, variable_dependencies=None):
        # Narrative dialogs belong to a thread and have an explicit position (order).
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.thread = thread
        self.position = position


class ChitchatDialog(ScriptedMiniDialog):
    # topics is a list — each element is indexed individually so get_by_attr("topics", "pizza")
    # returns all ChitchatDialogs whose topics list contains "pizza".
    INDEX_ATTRS: list[str] = ["topics"]
    DEFAULT_ELIGIBILITY = EligibilityPolicy([ExcludeIfSeenRule(), DepsMetRule(), VariableDepsMetRule()])
    dialog_type: DialogType = DialogType.CHITCHAT

    def __init__(self, dialog_id, moves, topics=None, dependencies=None, variable_dependencies=None):
        # Chitchat dialogs are short interactions labelled by topics for interest-based matching.
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.topics = topics or []


class LLMMiniDialog(MiniDialog):
    """Pure-data dialog driven entirely by a free-form multi-turn LLM conversation.

    Unlike ``ScriptedMiniDialog``, ``LLMMiniDialog`` carries no scripted move
    list — the runtime delegates fully to ``_run_llm_exchange``.  The ``moves``
    attribute is kept (always ``[]``) for serialisation round-trip compatibility
    with the authoring layer.
    """

    INDEX_ATTRS: list[str] = []
    DEFAULT_ELIGIBILITY = EligibilityPolicy([ExcludeIfSeenRule(), DepsMetRule(), VariableDepsMetRule()])
    dialog_type: DialogType = DialogType.LLM_BASED

    def __init__(self, dialog_id, moves=None, prompt=None, max_turns=None, dependencies=None,
                 variable_dependencies=None, quit_phrases: list[str] | None = None,
                 quit_signal: str | None = None, speak_first: bool = True,
                 duration: float | None = None, rag_enabled: bool = False,
                 index_name: str | None = None):
        super().__init__(dialog_id, dependencies, variable_dependencies)
        # moves is accepted for factory round-trip compat but unused at runtime
        self.moves: list[AnyMove] = list(moves or [])
        self.prompt = prompt
        self.max_turns = max_turns  # None means use MAX_LLM_TURNS default at runtime
        self.speak_first = speak_first
        self.duration = duration
        self.rag_enabled = rag_enabled
        self.index_name = index_name
        # Quit phrases (user utterances) and quit signal (LLM-inserted token)
        self.quit_phrases = [p for p in (quit_phrases or []) if p]
        self.quit_signal = quit_signal if quit_signal is not None else "<<QUIT>>"
