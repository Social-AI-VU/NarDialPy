import json
import logging
import os
import random
from typing import TYPE_CHECKING

from nardial.agenda import AgendaContext, resolve_agenda
from nardial.conversation_agent import ConversationAgent
from nardial.conversation_state import ConversationState, Session
from nardial.dialog_logic import DialogLogic
from nardial.dialog_registry import DialogRegistry
from nardial.mini_dialogs import RunContext

from nardial.authoring import load_dialogs

if TYPE_CHECKING:
    from nardial.agenda.session_plan import SessionPlan

logger = logging.getLogger(__name__)


class SessionManager:
    """Orchestrates a full conversational session by resolving the agenda
    incrementally, running each dialog, and persisting session state.

    The ``session_agenda`` accepts plain dialog ID strings (backward-compatible),
    typed ``AgendaItem`` objects, or dicts — all are coerced inside
    ``resolve_agenda()``.

    Parameters
    ----------
    session_agenda : list
        Ordered agenda items: plain dialog ID strings, ``AgendaItem`` objects,
        or dicts are all accepted.  Strings are coerced to ``DialogRef`` items
        at resolution time so existing call sites continue to work unchanged.
        Overridden by ``session_plan_path`` when a plan is provided.
    agent : ConversationAgent
        Responsible for interaction (speech, LLM, etc.).
    dialog_json_path : str
        Path to JSON file (or directory) containing dialog definitions.
    participant_id : str, optional
        Identifier for the user/participant.
    session_plan_path : str | None
        Path to a :class:`~nardial.agenda.session_plan.SessionPlan` JSON file.
        When provided, the plan's agenda for the current session overrides
        ``session_agenda``.
    session_index : int | None
        Force a specific 1-based session index when selecting a template from
        the plan, ignoring the participant's actual session count.  Only
        meaningful when ``session_plan_path`` is also provided.
    reset_history_from_session : int | None
        Truncate participant history from this 1-based session index onward
        before starting.  A warning is logged before the destructive operation.
    resume : bool
        If ``True``, check for an incomplete session (one with ``ended_at``
        still ``None``) and resume it by skipping already-completed dialogs.
        Proceeds as a fresh session when no incomplete session is found.
    """

    def __init__(
        self,
        session_agenda: list,
        agent: ConversationAgent,
        dialog_json_path: str,
        participant_id=None,
        session_plan_path: str | None = None,
        session_index: int | None = None,
        reset_history_from_session: int | None = None,
        resume: bool = False,
    ):
        self._registry = self.load_dialog_registry(dialog_json_path)
        self.agent = agent

        # Dialog IDs that were already run in an incomplete session; pre-populated
        # by _apply_resume() so _build_agenda_context() treats them as completed.
        self._resume_completed_ids: set[str] = set()

        self.conversation_state = ConversationState(participant_id=participant_id)

        # Apply history reset *before* counting sessions or loading the plan.
        if reset_history_from_session is not None:
            logger.warning(
                "Resetting participant history from session %d forward for participant %r",
                reset_history_from_session,
                participant_id,
            )
            self.conversation_state.truncate_from_session(reset_history_from_session)

        # Resolve agenda: session plan overrides the caller-supplied session_agenda.
        if session_plan_path is not None:
            plan_agenda = self._resolve_plan_agenda(session_plan_path, session_index)
            self.session_agenda = plan_agenda if plan_agenda is not None else session_agenda
        else:
            self.session_agenda = session_agenda

        # Handle crash recovery — must come after agenda resolution so the same
        # agenda is replayed on resume.
        if resume:
            incomplete = self.conversation_state.find_incomplete_session()
            if incomplete is not None:
                self.session_id = self._apply_resume(incomplete)
            else:
                logger.info(
                    "resume=True but no incomplete session found — proceeding as fresh session"
                )
                self.session_id = self.start_session()
        else:
            self.session_id = self.start_session()

    # ── Dialog loading ────────────────────────────────────────────────────────

    @staticmethod
    def load_dialogs_from_json(path):
        """Load dialogs from a JSON file using the authoring loader.

        Kept for backward compatibility and direct testing; ``load_dialog_registry``
        is the preferred entry point when only the registry is needed.

        Parameters
        ----------
        path : str
            Path to the dialog JSON file or directory.

        Returns
        -------
        list
            Loaded dialog objects, or an empty list if loading fails.
        """
        try:
            dialogs, errors = load_dialogs(path)
            if errors:
                logger.error("Failed to fully load dialogs: %s", errors)
                return []
            if dialogs:
                logger.info("Loaded %d dialogs from %s", len(dialogs), path)
                return dialogs
            return []
        except Exception as e:
            logger.error("Failed to load dialogs: %s", e)
            return []

    @staticmethod
    def load_dialog_registry(path) -> DialogRegistry:
        """Load dialogs from *path* and build an indexed ``DialogRegistry``.

        Parameters
        ----------
        path : str
            Path to the dialog JSON file or directory.

        Returns
        -------
        DialogRegistry
            Populated registry, or an empty registry on failure.
        """
        dialogs = SessionManager.load_dialogs_from_json(path)
        return DialogRegistry.build(dialogs)

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def start_session(self):
        """Initialise a new session in the conversation state.

        Generates or retrieves a run ID, registers the session, and logs it.

        Returns
        -------
        str
            The created session ID.
        """
        run_id = os.environ.get("RUN_ID") or f"run_{random.randint(0, 999_999):06d}"
        session_id = self.conversation_state.start_session(
            participant_id=self.conversation_state.participant_id,
            run_id=run_id,
        )
        logger.info("Started session_id=%s run_id=%s", session_id, run_id)
        return session_id

    # ── Plan resolution ───────────────────────────────────────────────────────

    def _resolve_plan_agenda(
        self,
        plan_path: str,
        override_index: int | None,
    ) -> list | None:
        """Load a :class:`SessionPlan` and return the raw agenda for the current session.

        The session number is determined by counting the participant's completed
        sessions and adding 1, unless *override_index* is supplied.

        Parameters
        ----------
        plan_path : str
            Path to the session plan JSON file.
        override_index : int | None
            Force this 1-based session index; ignored when ``None``.

        Returns
        -------
        list or None
            Raw agenda entries from the matching template, or ``None`` on error.
        """
        from nardial.agenda.session_plan import load_session_plan

        try:
            plan = load_session_plan(plan_path)
        except Exception as exc:
            logger.error("Failed to load session plan from %r: %s", plan_path, exc)
            return None

        session_number = (
            override_index
            if override_index is not None
            else self.conversation_state.count_completed_sessions() + 1
        )

        template = plan.get_template(session_number)
        if template is None:
            logger.warning(
                "SessionPlan '%s' returned no template for session_number=%d",
                plan.plan_id,
                session_number,
            )
            return None

        logger.info(
            "SessionPlan '%s': using template session_index=%d (session_number=%d)",
            plan.plan_id,
            template.session_index,
            session_number,
        )
        return template.agenda

    # ── Crash recovery ────────────────────────────────────────────────────────

    def _apply_resume(self, incomplete: Session) -> str:
        """Prepare to resume an incomplete session.

        Pre-populates :attr:`_resume_completed_ids` with the dialog IDs already
        run in *incomplete* so that :meth:`_build_agenda_context` skips them.
        Returns the existing session ID so the resumed session appends its new
        events to the same record rather than starting a fresh one.

        Parameters
        ----------
        incomplete : Session
            The last session for this participant, whose ``ended_at`` is
            ``None``.

        Returns
        -------
        str
            The session ID to reuse.
        """
        already_run = set(incomplete.dialog_ids or [])
        self._resume_completed_ids = already_run
        logger.info(
            "Resuming incomplete session %s — %d dialog(s) already completed: %s",
            incomplete.session_id,
            len(already_run),
            sorted(already_run),
        )
        return incomplete.session_id

    # ── Agenda resolution ─────────────────────────────────────────────────────

    def _build_agenda_context(self) -> AgendaContext:
        """Build an ``AgendaContext`` from the current conversation state.

        When a resume is in progress, the dialog IDs from the incomplete session
        are merged into both ``completed_ids`` and ``session_completed_ids`` so
        that eligibility rules correctly exclude already-run dialogs.

        Returns
        -------
        AgendaContext
            Context populated with the full registry and participant history.
        """
        return AgendaContext(
            registry=self._registry,
            completed_ids=set(self.conversation_state.completed_dialogs) | self._resume_completed_ids,
            session_completed_ids=set(self._resume_completed_ids),
            user_model=self.conversation_state.user_model,
            topics_of_interest=list(self.conversation_state.topics_of_interest),
        )

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self):
        """Execute the session by resolving the agenda incrementally.

        For each dialog yielded by ``resolve_agenda()``:

        1. A final eligibility check via ``DialogLogic.is_dialog_eligible()``
           guards against stale state (defense-in-depth).
        2. The dialog runs via ``dialog.run(agent, run_context)``.
        3. Completion is recorded in both the ``AgendaContext`` (so subsequent
           eligibility decisions in this session see fresh state) and the
           ``ConversationState`` (for cross-session persistence).

        Session events and topics are persisted at the end of the session.
        """
        run_context = RunContext(
            session_history=[],
            topics_of_interest=self.conversation_state.topics_of_interest,
            user_model=self.conversation_state.user_model,
        )

        context = self._build_agenda_context()

        for dialog in resolve_agenda(self.session_agenda, context):
            if not DialogLogic.is_dialog_eligible(
                dialog,
                context.completed_ids,
                context.user_model,
            ):
                logger.debug("Skipped %s (final eligibility gate failed)", dialog.dialog_id)
                continue

            self.conversation_state.add_dialog_id(self.session_id, dialog.dialog_id)

            run_context.session_history.append({
                "role": "system",
                "type": "dialog_start",
                "dialog_id": dialog.dialog_id,
            })

            dialog.run(self.agent, run_context)

            run_context.session_history.append({
                "role": "system",
                "type": "dialog_end",
                "dialog_id": dialog.dialog_id,
            })

            # Record completion in both the in-session context (for incremental
            # eligibility decisions) and the persistent conversation state.
            self.conversation_state.completed_dialogs.append(dialog.dialog_id)
            context.mark_completed(dialog.dialog_id)

        logger.debug("Session history:\n%s", json.dumps(run_context.session_history, indent=2))
        logger.debug("Topics of interest: %s", run_context.topics_of_interest)

        # Condense topics_of_interest into single-word keywords
        topics_of_interest = self.condense_topics(run_context.topics_of_interest)

        self.conversation_state.add_events(self.session_id, run_context.session_history)
        self.conversation_state.end_session(
            self.session_id,
            completed_ids=self.conversation_state.completed_dialogs,
            user_model=self.conversation_state.user_model,
            topics_of_interest=topics_of_interest,
        )
        self.conversation_state.save()

    def condense_topics(self, topics_of_interest):
        """Reduce a list of topics of interest into concise keywords using GPT.

        Falls back to the original list if extraction fails.

        Parameters
        ----------
        topics_of_interest : list[str]
            List of topic strings accumulated during the session.

        Returns
        -------
        list[str]
            Condensed list of topic keywords.
        """
        try:
            topics_of_interest = self.agent.extract_topics_with_llm(list(topics_of_interest))
            logger.debug("Condensed topics: %s", topics_of_interest)
        except Exception as e:
            logger.warning("Topic condensation failed: %s", e)
        return topics_of_interest
