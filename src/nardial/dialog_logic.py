import logging
import random
from nardial.mini_dialogs import NarrativeDialog, ChitchatDialog, FunctionalDialog, MiniDialog

logger = logging.getLogger(__name__)


class DialogLogic:
    """
    Utility class for selecting, filtering, and ordering dialogs.

    This class encapsulates the decision logic that determines:
    - Whether a dialog can run (`is_dialog_eligible`)
    - Which dialogs best match user interests
    - How to interleave narrative and chitchat dialogs
    - How to construct a full session flow

    It operates on collections of `MiniDialog` objects and uses:
    - Completed dialog history
    - User model variables
    - Topics of interest
    """

    @staticmethod
    def is_dialog_eligible(dialog, completed_ids, user_model, all_dialogs=None):
        """
        Determine whether a dialog can be executed.

        A dialog is considered eligible if:
        - It has not already been completed
        - All its dependencies are satisfied
        - Required user model variables are present
        - (For narrative dialogs) earlier steps in the same thread are completed

        Parameters
        ----------
        dialog : MiniDialog
            The dialog to evaluate.
        completed_ids : list or set of str
            Dialog IDs already completed.
        user_model : dict
            Current user state (used for variable dependencies).
        all_dialogs : list of MiniDialog, optional
            Full dialog set (required for narrative ordering checks).

        Returns
        -------
        bool
            True if the dialog can be executed, False otherwise.
        """
        if dialog.dialog_id in completed_ids:
            return False

        for dep in dialog.dependencies:
            if dep not in completed_ids:
                return False

        for var_dep in dialog.variable_dependencies:
            var = var_dep["variable"]
            required = var_dep.get("required", True)
            if required and not user_model.get(var):
                return False

        if isinstance(dialog, NarrativeDialog):
            if all_dialogs is None:
                all_dialogs = []
            for d in all_dialogs:
                if (isinstance(d, NarrativeDialog) and
                        d.thread == dialog.thread and
                        d.position < dialog.position and
                        d.dialog_id not in completed_ids):
                    return False

        return True

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
    def sort_chitchat_dialogs(pool, theme=None, topics_of_interest=None):
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
        theme : str, optional
            Restrict dialogs to a specific theme.
        topics_of_interest : list of str, optional
            User interest keywords.

        Returns
        -------
        list of ChitchatDialog
            Sorted list of candidate dialogs.
        Prioritize chitchat candidates by deps&interests > interests > deps > others
        """
        cands = [d for d in pool if isinstance(d, ChitchatDialog) and (theme is None or d.theme == theme)]
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
    def insert_chitchat_into_session(session, pool, theme=None, topics_of_interest=None, all_dialogs=None, completed_ids=None):
        """
        Attempt to insert a suitable chitchat dialog into the session.

        Handles:
        - Dependency resolution (including inserting prerequisite dialogs)
        - Continuity across sessions (completed_ids)
        - Greeting normalization (any greeting satisfies "greeting")

        Parameters
        ----------
        session : list of MiniDialog
            Current session sequence.
        pool : list of MiniDialog
            Remaining dialogs to choose from.
        theme : str, optional
            Preferred theme.
        topics_of_interest : list of str, optional
            User interests.
        all_dialogs : list of MiniDialog, optional
            Full dialog set.
        completed_ids : list or set, optional
            Previously completed dialogs.

        Returns
        -------
        bool
            True if a chitchat dialog was successfully inserted.
        """
        all_dialogs = all_dialogs or []
        cands = DialogLogic.sort_chitchat_dialogs(pool, theme=theme, topics_of_interest=topics_of_interest)

        if not cands:
            return False

        for c in cands:
            # Effective completion set: dialogs already in this session plus continuity
            completed_so_far = {d.dialog_id for d in session}
            effective_completed = set(completed_so_far)

            if completed_ids:
                effective_completed |= set(completed_ids)

            greeted = any(isinstance(d, FunctionalDialog) and d.is_greeting_dialog() for d in session)
            if greeted:
                effective_completed.add("greeting")

            if DialogLogic.is_dialog_eligible(c, effective_completed, user_model={}, all_dialogs=all_dialogs):
                session.append(c)
                pool.remove(c)
                return True

            for dep_id in getattr(c, "dependencies", []):
                dep = next((d for d in pool if d.dialog_id == dep_id), None)
                if not dep:
                    continue

                if DialogLogic.is_dialog_eligible(dep, effective_completed, user_model={}, all_dialogs=all_dialogs):
                    session.append(dep)
                    pool.remove(dep)
                    effective_completed.add(dep.dialog_id)

                    if DialogLogic.is_dialog_eligible(c, effective_completed, user_model={}, all_dialogs=all_dialogs):
                        session.append(c)
                        pool.remove(c)
                        return True

        return False

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

    @staticmethod
    def build_dialog_session(mini_dialogs, thread=None, theme=None, topics_of_interest=None, completed_ids=None):
        """
        Construct a full dialog session sequence.

        Default structure:
        1. Greeting
        2. Narrative step 1
        3. Chitchat
        4. Narrative step 2
        5. Chitchat
        6. Goodbye

        Parameters
        ----------
        mini_dialogs : list of MiniDialog
            All available dialogs.
        thread : str, optional
            Narrative thread to follow.
        theme : str, optional
            Preferred chitchat theme.
        topics_of_interest : list of str, optional
            User interests.
        completed_ids : list or set, optional
            Previously completed dialogs.

        Returns
        -------
        list of MiniDialog
            Ordered session plan.

        Notes
        -----
        - Ensures at least one greeting and one goodbye
        - Interleaves narrative and chitchat
        - Falls back gracefully if chitchat is unavailable
        """
        session = []
        pool = list(mini_dialogs)
        completed_ids = set(completed_ids or set())

        greeting = next(
            (d for d in pool if isinstance(d, FunctionalDialog) and d.is_greeting_dialog() and d.dialog_id not in completed_ids),
            None,
        )
        if not greeting:
            greeting = next((d for d in pool if isinstance(d, FunctionalDialog) and d.is_greeting_dialog()), None)

        if greeting:
            session.append(greeting)
            pool.remove(greeting)

        n1 = DialogLogic.select_next_narrative(pool, thread, completed_ids=completed_ids, user_model={},
                                               all_dialogs=mini_dialogs)
        if n1:
            session.append(n1)
            pool.remove(n1)

        added_c1 = DialogLogic.insert_chitchat_into_session(session, pool, theme=theme,
                                                            topics_of_interest=topics_of_interest,
                                                            all_dialogs=mini_dialogs,
                                                            completed_ids=completed_ids)
        if not added_c1:
            added_c1 = DialogLogic.insert_chitchat_into_session(session, pool, theme=None,
                                                                topics_of_interest=topics_of_interest,
                                                                all_dialogs=mini_dialogs,
                                                                completed_ids=completed_ids)
        if not added_c1:
            logger.info("Chitchats not available for this participant (after narrative 1).")

        n2 = DialogLogic.select_next_narrative(pool, thread,
                                               completed_ids=completed_ids.union({d.dialog_id for d in session}),
                                               user_model={}, all_dialogs=mini_dialogs)
        if n2:
            session.append(n2)
            pool.remove(n2)

        added_c2 = DialogLogic.insert_chitchat_into_session(session, pool,
                                                            theme=None if topics_of_interest else theme,
                                                            topics_of_interest=topics_of_interest,
                                                            all_dialogs=mini_dialogs,
                                                            completed_ids=completed_ids)
        if not added_c2:
            added_c2 = DialogLogic.insert_chitchat_into_session(session, pool, theme=theme,
                                                                topics_of_interest=topics_of_interest,
                                                                all_dialogs=mini_dialogs,
                                                                completed_ids=completed_ids)
        if not added_c2:
            logger.info("Chitchats not available for this participant (after narrative 2).")

        goodbye = next((d for d in pool if
                        isinstance(d, FunctionalDialog) and d.is_farewell_dialog() and d.dialog_id not in completed_ids),
                       None)
        if not goodbye:
            goodbye = next((d for d in pool if isinstance(d, FunctionalDialog) and d.is_farewell_dialog()), None)

        if goodbye:
            session.append(goodbye)

        return session