import logging
import random
from nardial.mini_dialogs import NarrativeDialog, ChitchatDialog

logger = logging.getLogger(__name__)


class DialogLogic:
    """
    Utility class for selecting, filtering, and ordering dialogs.

    This class encapsulates the decision logic that determines:
    - Whether a dialog can run (`is_dialog_eligible`)
    - Which dialogs best match user interests
    - How to interleave narrative and chitchat dialogs
    - How to construct a full session flow

    It operates on collections of dialog objects and uses:
    - Completed dialog history
    - User model variables
    - Topics of interest
    """

    @staticmethod
    def is_dialog_eligible(dialog, completed_ids, user_model, all_dialogs=None, policy=None):
        """
        Determine whether a dialog can be executed.

        Delegates to an ``EligibilityPolicy`` — a composable list of rules.
        When no policy is supplied, uses the class-level ``DEFAULT_ELIGIBILITY``
        policy attached to the dialog's class by ``nardial.eligibility``.

        Parameters
        ----------
        dialog : MiniDialog
            The dialog to evaluate.
        completed_ids : list or set of str
            Dialog IDs already completed (cross-session).
        user_model : dict
            Current user state (used for variable dependency checks).
        all_dialogs : list of MiniDialog, optional
            Full dialog set used to build a temporary registry for narrative
            ordering checks when no pre-built registry is available.
        policy : EligibilityPolicy, optional
            Custom policy; overrides the class default when supplied.

        Returns
        -------
        bool
            True if the dialog can be executed, False otherwise.
        """
        if policy is None:
            policy = type(dialog).DEFAULT_ELIGIBILITY

        # Build a minimal AgendaContext from the flat params so existing call
        # sites continue to work without a pre-built registry.
        from nardial.dialog_registry import DialogRegistry
        from nardial.agenda.items import AgendaContext
        registry = DialogRegistry.build(list(all_dialogs or []))
        context = AgendaContext(
            registry=registry,
            completed_ids=set(completed_ids),
            user_model=user_model or {},
        )
        return policy.is_eligible(dialog, context)

    @staticmethod
    def matches_user_interests(dialog, topics_of_interest):
        """
        Check whether a dialog aligns with the user's interests.

        Parameters
        ----------
        dialog : MiniDialog
            Dialog with optional `topics` attribute.
        topics_of_interest : list of str
            Known user interests.

        Returns
        -------
        bool
            True if at least one topic overlaps, or if no interests are defined.
        """
        # checks if the dialog has at least one topic that matches the user's topics of interest
        if not topics_of_interest:
            return True

        interests = [str(t).lower() for t in topics_of_interest]
        dialog_topics = [str(t).lower() for t in getattr(dialog, "topics", [])]

        return any(topic in interests for topic in dialog_topics)

    @staticmethod
    def sort_chitchat_dialogs(pool, topics_of_interest=None):
        """
        Rank chitchat dialogs by relevance and readiness.

        Priority order:
        1. Matches dependencies AND user interests
        2. Matches user interests
        3. Has dependencies satisfied
        4. Others

        Parameters
        ----------
        pool : list of MiniDialog
            Available dialogs.
        topics_of_interest : list of str, optional
            User interest keywords.

        Returns
        -------
        list of ChitchatDialog
            Sorted list of candidate dialogs.
        Prioritize chitchat candidates by deps&interests > interests > deps > others
        """
        cands = [d for d in pool if isinstance(d, ChitchatDialog)]
        if not cands:
            return []

        random.shuffle(cands)

        def score(d):
            has_deps = 1 if getattr(d, "dependencies", []) else 0
            has_interest = 1 if (topics_of_interest and DialogLogic.matches_user_interests(d, topics_of_interest)) else 0
            return (has_deps & has_interest, has_interest, has_deps)

        return sorted(cands, key=score, reverse=True)

    @staticmethod
    def select_active_thread(mini_dialogs, preferred_thread, completed_ids, user_model):
        """
        Select a narrative thread that still has runnable dialogs.

        Strategy:
        - Try the preferred thread first
        - Otherwise, pick any thread with remaining runnable dialogs

        Parameters
        ----------
        mini_dialogs : list of MiniDialog
            All dialogs.
        preferred_thread : str
            Preferred narrative thread.
        completed_ids : list or set
            Completed dialog IDs.
        user_model : dict
            Current user state.

        Returns
        -------
        str or None
            Selected thread name, or None if no valid thread exists.
        """
        pool = list(mini_dialogs)

        if preferred_thread:
            if DialogLogic.select_next_narrative(pool, preferred_thread,
                                                 completed_ids=completed_ids,
                                                 user_model=user_model,
                                                 all_dialogs=mini_dialogs):
                return preferred_thread

        threads = []
        for d in mini_dialogs:
            if isinstance(d, NarrativeDialog) and d.thread not in threads:
                threads.append(d.thread)

        random.shuffle(threads)

        for t in threads:
            if t == preferred_thread:
                continue
            if DialogLogic.select_next_narrative(pool, t,
                                                 completed_ids=completed_ids,
                                                 user_model=user_model,
                                                 all_dialogs=mini_dialogs):
                return t

        return None

    @staticmethod
    def select_next_narrative(pool, thread, completed_ids, user_model, all_dialogs):
        """
        Select the next narrative dialog in a thread.

        Chooses the lowest-position dialog that is eligible and not yet completed.

        Parameters
        ----------
        pool : list of MiniDialog
            Available dialogs.
        thread : str
            Narrative thread identifier.
        completed_ids : list or set
            Completed dialog IDs.
        user_model : dict
            Current user state.
        all_dialogs : list of MiniDialog
            Full dialog set.

        Returns
        -------
        NarrativeDialog or None
        """
        candidates = [d for d in pool if isinstance(d, NarrativeDialog) and d.thread == thread]
        candidates.sort(key=lambda d: d.position)

        for d in candidates:
            if DialogLogic.is_dialog_eligible(d, completed_ids, user_model, all_dialogs=all_dialogs):
                return d

        return None

