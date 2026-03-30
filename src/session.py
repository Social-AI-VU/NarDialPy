from typing import Any, Dict, List, Optional, Set, Union

from src.mini_dialogs import MiniDialog


class Dialog:
    """
    Represents a planned conversation dialog composed of an ordered sequence of
    mini-dialogs.

    A Dialog is built by ``DialogLogic.build_dialog`` and holds the mini-dialogs
    to be executed in sequence, along with metadata about the narrative thread
    and theme.
    """

    def __init__(
        self,
        mini_dialogs: List[MiniDialog],
        thread: Optional[str] = None,
        theme: Optional[str] = None,
    ):
        self.mini_dialogs: List[MiniDialog] = list(mini_dialogs)
        self.thread: Optional[str] = thread
        self.theme: Optional[str] = theme

    def __iter__(self):
        return iter(self.mini_dialogs)

    def __len__(self) -> int:
        return len(self.mini_dialogs)

    def __repr__(self) -> str:
        ids = [d.dialog_id for d in self.mini_dialogs]
        return f"Dialog(thread={self.thread!r}, theme={self.theme!r}, mini_dialogs={ids})"


class Session:
    """
    Manages the execution state and progression of a :class:`Dialog`.

    A Session takes a Dialog and executes its mini-dialogs in order using a
    conversation agent.  It tracks which mini-dialogs have been completed, the
    evolving user model, accumulated topics of interest, and the full
    conversation history.

    Attributes:
        dialog: The :class:`Dialog` this session will execute.
        completed_dialogs: Set of dialog IDs that have been run (pre-existing
            continuity plus any dialogs completed during this session).
        user_model: Key/value map of participant variables (updated in-place
            by mini-dialogs as they run).
        topics_of_interest: List of interest topics accumulated during the
            session (updated in-place by mini-dialogs as they run).
        history: Ordered list of conversation events recorded during
            :meth:`run`.
        executed_dialog_ids: Ordered list of dialog IDs that were actually
            executed during :meth:`run` (dialogs skipped due to unmet
            dependencies are excluded).
    """

    def __init__(
        self,
        dialog: Dialog,
        completed_dialogs: Optional[Union[Set[str], List[str]]] = None,
        user_model: Optional[Dict[str, Any]] = None,
        topics_of_interest: Optional[List[str]] = None,
    ):
        self.dialog = dialog
        self.completed_dialogs: Set[str] = set(completed_dialogs) if completed_dialogs else set()
        self.user_model: Dict[str, Any] = dict(user_model) if user_model else {}
        self.topics_of_interest: List[str] = list(topics_of_interest) if topics_of_interest else []
        self.history: List[Dict[str, Any]] = []
        self.executed_dialog_ids: List[str] = []

    def run(
        self,
        agent,
        all_dialogs: Optional[List[MiniDialog]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute all mini-dialogs in the session's :attr:`dialog`.

        Only mini-dialogs whose dependencies are satisfied (via
        ``DialogLogic.can_run``) are executed; others are skipped with a debug
        message.  The :attr:`completed_dialogs`, :attr:`user_model`, and
        :attr:`topics_of_interest` attributes are updated as each mini-dialog
        runs.

        Args:
            agent: The conversation agent used to speak and listen.
            all_dialogs: Full catalog of mini-dialogs, used for dependency
                resolution.  Defaults to ``None`` (no catalog-level checks).

        Returns:
            The accumulated conversation :attr:`history` for this session.
        """
        # Local import to avoid a circular import between session and dialog.
        from src.dialog import DialogLogic

        for mini_dialog in self.dialog:
            if not DialogLogic.can_run(
                mini_dialog, self.completed_dialogs, self.user_model, all_dialogs
            ):
                print(f"[DEBUG] Skipped {mini_dialog.dialog_id} (cannot run now)")
                continue

            self.history.append(
                {"role": "system", "type": "dialog_start", "dialog_id": mini_dialog.dialog_id}
            )
            mini_dialog.run(agent, self.history, self.topics_of_interest, self.user_model)
            self.history.append(
                {"role": "system", "type": "dialog_end", "dialog_id": mini_dialog.dialog_id}
            )
            self.completed_dialogs.add(mini_dialog.dialog_id)
            self.executed_dialog_ids.append(mini_dialog.dialog_id)

        return self.history
