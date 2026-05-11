"""Dialog checkpoints for pause-and-resume across event interruptions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScriptedMiniDialogCheckpoint:
    """Resumption state for a scripted (ScriptedMiniDialog) execution.

    Attributes
    ----------
    dialog_id : str
        ID of the interrupted dialog.
    move_index : int
        Index of the *next* move to execute on resume.  All moves before
        this index have already completed successfully.
    current_outcome : str or None
        The ``context.current_outcome`` at the point of interruption, so
        branching logic is replayed correctly on resume.
    """

    dialog_id: str
    move_index: int
    current_outcome: str | None = None


@dataclass
class LLMMiniDialogCheckpoint:
    """Resumption state for a free-form LLM dialog execution.

    Attributes
    ----------
    dialog_id : str
        ID of the interrupted dialog.
    dialog_history : list of str
        User utterances accumulated so far (passed as ``context_messages``
        on the next LLM call).
    turn_index : int
        Number of LLM turns already completed.
    last_user_input : str
        The last user utterance received before interruption.
    elapsed_seconds : float
        Wall-clock time already spent in the dialog (for duration budgets).
    """

    dialog_id: str
    dialog_history: list[str] = field(default_factory=list)
    turn_index: int = 0
    last_user_input: str = ""
    elapsed_seconds: float = 0.0


#: Union type alias for any checkpoint variant.
AnyCheckpoint = ScriptedMiniDialogCheckpoint | LLMMiniDialogCheckpoint
