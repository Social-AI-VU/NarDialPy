import json
import os

import numpy as np
import asyncio

from nardial.agenda.items import AgendaContext
from nardial.agenda.resolver import resolve_agenda
from nardial.agenda.session_plan import load_session_plan
from nardial.conversation_agent import ConversationAgent
from nardial.conversation_state import ConversationState
from nardial.dialog_registry import DialogRegistry
from nardial.eligibility import is_dialog_eligible

from nardial.authoring import load_dialog_registry, load_dialog_types
from nardial.events import EventBus


class SessionManager:
    """
    Orchestrates a full conversational session by selecting, running,
    and logging dialogs according to a session agenda and conversation state.
    """

    def __init__(self, session_agenda: list, agent: ConversationAgent, dialog_json_path: str, participant_id=None,
                 session_plan_path=None, session_index=None, reset_history_from_session=None, resume: bool = False,
                 dialog_types_path=None):
        """
        Initialize a session manager.

        :param session_agenda: Ordered list of dialog IDs and/or agenda item
            dicts/AgendaItem instances to resolve via `resolve_agenda()`. An
            empty list runs every loaded dialog, in loaded order.
        :param agent: ConversationAgent responsible for interaction (speech, LLM, etc.).
        :param dialog_json_path: Path to JSON file or directory containing dialog definitions.
        :param participant_id: Optional identifier for the user/participant.
        :param session_plan_path: Optional path to a `SessionPlan` JSON file. When
            set, the template picked for this participant's current session number
            overrides `session_agenda`; falls back to `session_agenda` unchanged if
            the plan fails to load or defines no templates.
        :param session_index: Overrides the auto-detected session number used to pick a
            `SessionPlan` template and exposed to eligibility rules as
            `AgendaContext.session_index`.
        :param reset_history_from_session: When set, destructively truncates this
            participant's persisted history from this 1-based session number onward
            before the new session starts. Irreversible.
        :param resume: When True, checks for an incomplete session (one whose `ended_at`
            is still `None`, e.g. left behind by a crash) and resumes it by reusing its
            session id and skipping the dialogs it already ran. Proceeds as a fresh
            session when no incomplete session is found.
        :param dialog_types_path: Optional path to a JSON file or directory of custom
            dialog type definitions (`define_type` docs). Loaded before the dialogs in
            `dialog_json_path`, which may then use these types.
        """
        self.session_agenda = session_agenda
        self.dialog_types_path = dialog_types_path
        if dialog_types_path:
            self.load_dialog_types_from_json(dialog_types_path)
        self.registry = self.load_dialog_registry_from_json(dialog_json_path)
        self.agent = agent

        self.session_plan_path = session_plan_path
        self.session_index = session_index
        self.reset_history_from_session = reset_history_from_session
        self.resume = resume
        # Dialog ids already run in an incomplete session being resumed; kept
        # separate from conversation_state.completed_dialogs (see
        # _build_agenda_context()) so a crash-free session behaves identically
        # to before this attribute existed.
        self._resume_completed_ids: set = set()

        self.conversation_state = ConversationState(participant_id=participant_id)

        if self.reset_history_from_session is not None:
            print(f"[WARN] Destructively resetting history for participant_id={participant_id!r} "
                  f"from session {self.reset_history_from_session} onward. This cannot be undone.")
            self.conversation_state.truncate_from_session(self.reset_history_from_session)

        if self.resume:
            incomplete = self.conversation_state.find_incomplete_session()
            if incomplete is not None:
                # find_incomplete_session() reads it from the persisted
                # transcript, not from conversation_state.sessions (which is
                # empty on a fresh instance) -- register it in-memory too, or
                # every later add_dialog_id()/add_events()/end_session() call
                # for this session_id raises KeyError.
                self.conversation_state.sessions.append(incomplete)
                self.session_id = incomplete.session_id
                self._resume_completed_ids = set(incomplete.dialog_ids or [])
                print(f"[INFO] Resuming incomplete session_id={self.session_id}; "
                      f"{len(self._resume_completed_ids)} dialog(s) already completed: "
                      f"{sorted(self._resume_completed_ids)}")
            else:
                print("[INFO] resume=True but no incomplete session was found; starting a fresh session.")
                self.session_id = self.start_session()
        else:
            self.session_id = self.start_session()

        if self.session_plan_path:
            plan_agenda = self._resolve_session_plan_agenda()
            if plan_agenda is not None:
                self.session_agenda = plan_agenda

        self._bus = None

    @staticmethod
    def load_dialog_types_from_json(path):
        """
        Register the custom dialog types defined in a JSON file or directory.

        Errors are logged; types that loaded successfully stay registered.

        :param path: Path to the dialog types JSON file or directory.
        :return: List of registered dialog type classes.
        """
        types, errors = load_dialog_types(path)
        if errors:
            print("[ERROR] Failed to fully load dialog types:", errors)
        print(f"[INFO] Loaded {len(types)} dialog types from {path}")
        return types

    @staticmethod
    def load_dialog_registry_from_json(path):
        """
        Load a DialogRegistry from a JSON file or directory using the authoring loader.

        Per-file/per-doc errors are logged but never discard dialogs that
        loaded successfully (unlike the old all-or-nothing `load_dialogs()`
        wrapper this replaces).

        :param path: Path to the dialog JSON file or directory.
        :return: DialogRegistry (possibly partially populated if some files/docs failed).
        """
        try:
            registry, errors = load_dialog_registry(path)
            if errors:
                print("[ERROR] Failed to fully load dialogs:", errors)
            print(f"[INFO] Loaded {len(registry.by_id)} dialogs from {path}")
            return registry
        except Exception as e:
            print(f"[ERROR] Failed to load dialogs: {e}")
            return DialogRegistry()

    def start_session(self):
        """
        Initialize a new session in the conversation state.

        Generates or retrieves a run ID, registers the session, and logs it.

        :return: The created session ID.
        """
        run_id = os.environ.get("RUN_ID") or f"run_{np.random.randint(1_000_000):06d}"
        session_id = self.conversation_state.start_session(
            participant_id=self.conversation_state.participant_id,
            run_id=run_id
        )
        print(f"[INFO] Started session_id={session_id} run_id={run_id}")
        return session_id

    def _current_session_number(self) -> int:
        """1-indexed session number for the session that was just started.

        `start_session()` already appended the current session to
        `conversation_state.sessions` before this is ever called, so this is
        simply its length -- adding 1 here would double count the current
        session (the off-by-one this method exists to avoid).
        """
        return len(self.conversation_state.sessions)

    def _session_number(self) -> int:
        """Session number used for plan templates and session-based eligibility rules.

        `session_index`, when set, overrides the auto-detected number.
        """
        return self.session_index if self.session_index is not None else self._current_session_number()

    def _resolve_session_plan_agenda(self):
        """Resolve this session's agenda from `session_plan_path`, if set.

        Returns `None` (leaving `session_agenda` as given) when no plan path
        was set, the plan fails to load, or it defines no templates at all.
        `session_index`, when set, overrides the auto-detected session number.
        """
        plan, errors = load_session_plan(self.session_plan_path)
        if errors:
            print(f"[ERROR] Problems loading session plan {self.session_plan_path}:", errors)
        if plan is None:
            return None

        session_number = self._session_number()
        template = plan.get_template(session_number)
        if template is None:
            print(f"[WARN] Session plan {plan.plan_id!r} has no templates; keeping the given session_agenda.")
            return None

        print(f"[INFO] Session plan {plan.plan_id!r}: using template for "
              f"session_index={template.session_index} (session_number={session_number})")
        return template.agenda

    def _build_agenda_context(self) -> AgendaContext:
        """Assemble the AgendaContext resolve_agenda() resolves this session's agenda against.

        `completed_ids` and `topics_of_interest` are the same mutable objects
        `conversation_state` and dialog moves already read/write, so
        `context.mark_completed()` and in-dialog interest tracking stay in
        sync with the rest of session bookkeeping without any extra copying.

        When resuming an incomplete session, dialogs already run before the
        crash (`_resume_completed_ids`) are folded into `completed_ids` as a
        fresh list -- not by mutating `conversation_state.completed_dialogs`
        itself -- so the normal `ExcludeIfSeenRule` machinery treats them as
        already done, same as it would for a prior session's completions.
        They're also exposed via `session_completed_ids` directly. A
        crash-free session (`_resume_completed_ids` empty) is unaffected:
        `completed_ids` stays the same object as before.
        """
        completed_ids = self.conversation_state.completed_dialogs
        if self._resume_completed_ids:
            completed_ids = list(completed_ids) + [
                dialog_id for dialog_id in self._resume_completed_ids if dialog_id not in completed_ids
            ]
        return AgendaContext(
            registry=self.registry,
            completed_ids=completed_ids,
            session_completed_ids=list(self._resume_completed_ids),
            user_model=self.conversation_state.user_model,
            topics_of_interest=self.conversation_state.topics_of_interest,
            session_index=self._session_number(),
        )

    def run(self):
        """Run the session synchronously and ensure a graceful shutdown.

        This wraps asyncio.run(self.run_async()) and guarantees that the
        agent's orchestrator is disconnected (providers closed) even if
        the session raises an exception.
        """
        try:
            asyncio.run(self.run_async())
        finally:
            # Attempt best-effort graceful shutdown of provider resources.
            try:
                if hasattr(self.agent, "orchestrator") and self.agent.orchestrator is not None:
                    try:
                        # Stop any logging thread first (if used)
                        if hasattr(self.agent.orchestrator, "stop_logging"):
                            try:
                                self.agent.orchestrator.stop_logging()
                            except Exception:
                                pass
                        # Disconnect providers (TTS, device, vector store, screen)
                        if hasattr(self.agent.orchestrator, "disconnect"):
                            self.agent.orchestrator.disconnect()
                    except Exception:
                        # Swallow errors during shutdown but print for debug
                        print("[WARN] Error while disconnecting orchestrator:", end=" ")
                        import traceback
                        traceback.print_exc()
            except Exception:
                pass

    async def run_async(self):
        """
        Execute the session by running each dialog in sequence.

        Handles:
        - Eligibility checks via EligibilityPolicy
        - Session history tracking
        - Updating conversation state (completed dialogs, topics, user model)
        - Persisting session results
        """

        self._bus = EventBus()
        # set_loop must happen before any source task starts so that emit_sync()
        # calls from callback threads (e.g. robot SDK) have a valid loop reference.
        self._bus.set_loop(asyncio.get_running_loop())
        sp = self.agent.orchestrator.screen_provider
        if sp is not None and hasattr(sp, "set_event_bus"):
            sp.set_event_bus(self._bus)

        # An empty agenda runs every loaded dialog, in loaded order (same
        # fallback build_session_block() used to provide).
        agenda = self.session_agenda if self.session_agenda else list(self.registry.by_id.keys())
        if not self.session_agenda:
            print("[INFO] Session agenda is empty, running all dialogs.")

        session_history = []
        context = self._build_agenda_context()
        for dialog in resolve_agenda(agenda, context):
            # Final safety-net gate: resolve_agenda() already checks eligibility
            # for slot-based agenda items, but a plain dialog id (DialogRef)
            # resolves regardless of eligibility, so this still guards every
            # existing list[str] agenda. The explicit session_completed_ids
            # check additionally catches a resumed session's already-run
            # dialogs even when the dialog type's own DEFAULT_ELIGIBILITY has
            # no ExcludeIfSeenRule at all (e.g. FunctionalDialog) -- outside
            # of a resume, session_completed_ids only ever contains dialogs
            # this same loop already ran, so this is a no-op for a normal
            # session.
            if not is_dialog_eligible(dialog, context) or dialog.dialog_id in context.session_completed_ids:
                print(f"[DEBUG] Skipped {dialog.dialog_id} (cannot run now)")
                continue

            self.conversation_state.add_dialog_id(self.session_id, dialog.dialog_id)

            session_history.append({
                "role": "system",
                "type": "dialog_start",
                "dialog_id": dialog.dialog_id
            })

            dialog.set_event_bus(self._bus)

            # dialog.run is async; await it directly inside the session event loop.
            try:
                await dialog.run(
                    self.agent,
                    session_history,
                    self.conversation_state.topics_of_interest,
                    self.conversation_state.user_model,
                    self.registry
                )
            except Exception as e:
                print(f"[ERROR] Running dialog {dialog.dialog_id} failed: {e}")

            session_history.append({
                "role": "system",
                "type": "dialog_end",
                "dialog_id": dialog.dialog_id
            })

            self.conversation_state.completed_dialogs.append(dialog.dialog_id)
            context.mark_completed(dialog.dialog_id)

        print(json.dumps(session_history, indent=2))
        print("Topics of interest:", self.conversation_state.topics_of_interest)

        # Condense topics_of_interest into single-word keywords
        topics_of_interest = await self.condense_topics(self.conversation_state.topics_of_interest)

        self.conversation_state.add_events(self.session_id, session_history)
        self.conversation_state.end_session(
            self.session_id,
            completed_ids=self.conversation_state.completed_dialogs,
            user_model=self.conversation_state.user_model,
            topics_of_interest=topics_of_interest
        )
        self.conversation_state.save()

    async def condense_topics(self, topics_of_interest):
        """
        Reduce a list of topics of interest into concise keywords using GPT.

        Falls back to the original list if extraction fails.

        :param topics_of_interest: List of topic strings.
        :return: Condensed list of topic keywords.
        """
        try:
            result = await self.agent.extract_topics_with_llm(list(topics_of_interest))
            print(f"[DEBUG] Condensed topics: {result}")
            return result
        except Exception as e:
            print(f"[WARN] Topic condensation failed: {e}")
            return topics_of_interest
