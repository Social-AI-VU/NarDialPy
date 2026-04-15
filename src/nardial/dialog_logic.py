import random
from nardial.mini_dialogs import NarrativeDialog, ChitchatDialog, FunctionalDialog, MiniDialog


class DialogLogic:
    @staticmethod
    def is_dialog_eligible(dialog, completed_ids, user_model, all_dialogs=None):
        # check if dialog can be run based on dependencies and user model variables
        # if narrative dialog, check position in thread and if previous narratives in thread have been completed
        # Block any dialog that is already completed (including greeting/farewell)
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
        # checks if the dialog has at least one topic that matches the user’s topics of interest
        if not topics_of_interest:
            return True
        interests = [str(t).lower() for t in topics_of_interest]
        dialog_topics = [str(t).lower() for t in getattr(dialog, "topics", [])]
        return any(topic in interests for topic in dialog_topics)

    @staticmethod
    def sort_chitchat_dialogs(pool, theme=None, topics_of_interest=None):
        """
        Prioritize chitchat candidates by deps∧interests > interests > deps > others
        """
        cands = [d for d in pool if isinstance(d, ChitchatDialog) and (theme is None or d.theme == theme)]
        if not cands:
            return []
        random.shuffle(cands)  # randomize within same priority

        def score(d):
            has_deps = 1 if getattr(d, "dependencies", []) else 0
            has_interest = 1 if (topics_of_interest and DialogLogic.matches_user_interests(d, topics_of_interest)) else 0
            # tuple sorted descending: (deps&interest, interest, deps)
            return (has_deps & has_interest, has_interest, has_deps)

        return sorted(cands, key=score, reverse=True)

    @staticmethod
    def select_active_thread(mini_dialogs, preferred_thread, completed_ids, user_model):
        """
        Pick a narrative thread that still has a runnable next dialog.
        - Try the preferred_thread first.
        - Otherwise, scan all threads and pick the first with a runnable next narrative.
        Returns the chosen thread name, or None if no thread has pending items.
        """
        pool = list(mini_dialogs)
        # Try preferred first
        if preferred_thread:
            if DialogLogic.select_next_narrative(pool, preferred_thread, completed_ids=completed_ids,
                                                 user_model=user_model, all_dialogs=mini_dialogs):
                return preferred_thread
        # Try any other thread
        threads = []
        for d in mini_dialogs:
            if isinstance(d, NarrativeDialog) and d.thread not in threads:
                threads.append(d.thread)
        # randomize to avoid always picking the same fallback
        random.shuffle(threads)
        for t in threads:
            if t == preferred_thread:
                continue
            if DialogLogic.select_next_narrative(pool, t, completed_ids=completed_ids, user_model=user_model,
                                                 all_dialogs=mini_dialogs):
                return t
        return None

    @staticmethod
    def insert_chitchat_into_session(session, pool, theme=None, topics_of_interest=None, all_dialogs=None, completed_ids=None):
        """
        Try to schedule one chitchat into session from pool.
        Improvements:
        - Treat any executed greeting variant as satisfying a "greeting" dependency.
        - Consider continuity (completed_ids) so chitchats can run even if greeting
          isn't scheduled in this session because it was done in a previous run.
        """
        all_dialogs = all_dialogs or []
        cands = DialogLogic.sort_chitchat_dialogs(pool, theme=theme, topics_of_interest=topics_of_interest)
        if not cands:
            return False
        for c in cands:
            # Effective completion set: dialogs already in this session ∪ continuity
            completed_so_far = {d.dialog_id for d in session}
            effective_completed = set(completed_so_far)
            if completed_ids:
                effective_completed |= set(completed_ids)
            # If any greeting variant ran in-session, satisfy generic "greeting" deps
            greeted = any(isinstance(d, FunctionalDialog) and d.is_greeting_dialog() for d in session)
            if greeted:
                effective_completed.add("greeting")

            if DialogLogic.is_dialog_eligible(c, effective_completed, user_model={}, all_dialogs=all_dialogs):
                session.append(c);
                pool.remove(c)
                return True
            # try to insert one runnable dependency first, then the candidate
            for dep_id in getattr(c, "dependencies", []):
                dep = next((d for d in pool if d.dialog_id == dep_id), None)
                if not dep:
                    continue
                if DialogLogic.is_dialog_eligible(dep, effective_completed, user_model={}, all_dialogs=all_dialogs):
                    session.append(dep);
                    pool.remove(dep)
                    effective_completed.add(dep.dialog_id)
                    if DialogLogic.is_dialog_eligible(c, effective_completed, user_model={}, all_dialogs=all_dialogs):
                        session.append(c);
                        pool.remove(c)
                        return True
                    # if still not runnable, continue trying other candidates
        return False

    @staticmethod
    def select_next_narrative(pool, thread, completed_ids, user_model, all_dialogs):
        """
        Pick the next runnable narrative in thread (lowest position not yet completed).
        Returns a dialog or None.
        """
        candidates = [d for d in pool if isinstance(d, NarrativeDialog) and d.thread == thread]
        candidates.sort(key=lambda d: d.position)
        for d in candidates:
            if DialogLogic.is_dialog_eligible(d, completed_ids, user_model, all_dialogs=all_dialogs):
                return d
        return None

    @staticmethod
    def build_dialog_session(mini_dialogs, thread=None, theme=None, topics_of_interest=None, completed_ids=None):
        session = []
        pool = list(mini_dialogs)
        completed_ids = set(completed_ids or set())
        # 1) Greeting: prefer a not-yet-used variant; otherwise include any greeting variant so we always greet
        greeting = next((d for d in pool if
                         isinstance(d, FunctionalDialog) and d.type == "greeting" and d.dialog_id not in completed_ids),
                        None)
        if not greeting:
            greeting = next((d for d in pool if isinstance(d, FunctionalDialog) and d.is_greeting_dialog()), None)
        if greeting:
            session.append(greeting)
            pool.remove(greeting)
        # 2) First narrative in thread
        n1 = DialogLogic.select_next_narrative(pool, thread, completed_ids=completed_ids, user_model={},
                                               all_dialogs=mini_dialogs)
        if n1:
            session.append(n1)
            pool.remove(n1)
        # 3) One themed chitchat (use continuity-aware scheduling); if none runnable, print notice
        added_c1 = DialogLogic.insert_chitchat_into_session(session, pool, theme=theme, topics_of_interest=topics_of_interest,
                                                            all_dialogs=mini_dialogs, completed_ids=completed_ids)
        if not added_c1:
            # Try relaxing theme once before giving up for this slot
            added_c1 = DialogLogic.insert_chitchat_into_session(session, pool, theme=None, topics_of_interest=topics_of_interest,
                                                                all_dialogs=mini_dialogs, completed_ids=completed_ids)
        if not added_c1:
            print("[INFO] Chitchats not available for this participant (after narrative 1).")
        # 4) Next narrative in same thread
        n2 = DialogLogic.select_next_narrative(pool, thread,
                                               completed_ids=completed_ids.union({d.dialog_id for d in session}),
                                               user_model={}, all_dialogs=mini_dialogs)
        if n2:
            session.append(n2)
            pool.remove(n2)
        # 5) Another themed chitchat; if none runnable, print notice
        added_c2 = DialogLogic.insert_chitchat_into_session(session, pool, theme=None if topics_of_interest else theme,
                                                            topics_of_interest=topics_of_interest, all_dialogs=mini_dialogs,
                                                            completed_ids=completed_ids)
        if not added_c2:
            added_c2 = DialogLogic.insert_chitchat_into_session(session, pool, theme=theme, topics_of_interest=topics_of_interest,
                                                                all_dialogs=mini_dialogs, completed_ids=completed_ids)
        if not added_c2:
            print("[INFO] Chitchats not available for this participant (after narrative 2).")

        # 6) Goodbye: prefer a not-yet-used variant; otherwise include any farewell variant so we always close politely
        goodbye = next((d for d in pool if
                        isinstance(d, FunctionalDialog) and d.is_farewell_dialog() and d.dialog_id not in completed_ids),
                       None)
        if not goodbye:
            goodbye = next((d for d in pool if isinstance(d, FunctionalDialog) and d.is_farewell_dialog()), None)
        if goodbye:
            session.append(goodbye)
        return session
