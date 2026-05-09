import json
import logging
import os
import random

from nardial.agenda import AgendaContext, resolve_agenda
from nardial.conversation_agent import ConversationAgent
from nardial.conversation_state import ConversationState
from nardial.dialog_logic import DialogLogic
from nardial.dialog_registry import DialogRegistry
from nardial.mini_dialogs import RunContext

from nardial.authoring import load_dialogs

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
    agent : ConversationAgent
        Responsible for interaction (speech, LLM, etc.).
    dialog_json_path : str
        Path to JSON file (or directory) containing dialog definitions.
    participant_id : str, optional
        Identifier for the user/participant.
    session_plan_path : str | None
        Reserved for issue #108 (multi-session arc JSON).
    session_index : int | None
        Reserved for issue #108.
    reset_history_from_session : int | None
        Reserved for issue #108.
    resume : bool
        Reserved for issue #109.
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
        self.session_agenda = session_agenda
        self._registry = self.load_dialog_registry(dialog_json_path)
        self.agent = agent

        self.conversation_state = ConversationState(participant_id=participant_id)
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

    # ── Agenda resolution ─────────────────────────────────────────────────────

    def _build_agenda_context(self) -> AgendaContext:
        """Build an ``AgendaContext`` from the current conversation state.

        Returns
        -------
        AgendaContext
            Context populated with the full registry and participant history.
        """
        return AgendaContext(
            registry=self._registry,
            completed_ids=set(self.conversation_state.completed_dialogs),
            session_completed_ids=set(),
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
