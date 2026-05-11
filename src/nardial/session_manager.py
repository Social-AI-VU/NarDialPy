import asyncio
import json
import logging
import os
import random
from typing import TYPE_CHECKING

from nardial.agenda import AgendaContext, resolve_agenda
from nardial.conversation_agent import ConversationAgent
from nardial.conversation_state import ConversationState, Session
from nardial.dialog_registry import DialogRegistry
from nardial.dialog_runtime import DialogRuntime, RunContext

from nardial.authoring import load_dialogs

from nardial.events.bus import EventBus
from nardial.events.types import InterruptLevel, ResumePolicy

if TYPE_CHECKING:
    from nardial.agenda.session_plan import SessionPlan
    from nardial.events.checkpoint import AnyCheckpoint
    from nardial.events.source import EventSource
    from nardial.events.specs import EventHandlerSpec
    from nardial.events.types import Event

logger = logging.getLogger(__name__)

_WATCHDOG_POLL_INTERVAL = 0.05  # seconds between immediate-interrupt polls


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

        # Event infrastructure — populated by add_event_source / add_event_handler
        # and by _resolve_plan_agenda() when a session plan declares sources/handlers.
        # Wired into the async run loop in Phase 8 (run_async / _dialog_loop).
        self._event_sources: list["EventSource"] = []
        self._event_handlers: dict[str, "EventHandlerSpec"] = {}
        # Set by run_async(); None until the session is actually running.
        self._bus: EventBus | None = None
        # Set by _immediate_watchdog when an IMMEDIATE event cancels a dialog task;
        # read and cleared by _dialog_loop to distinguish watchdog-triggered
        # CancelledErrors from outer session cancellations.
        self._last_immediate_event: "Event | None" = None

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

        # Register any event handlers and sources declared in the plan.
        self._register_plan_events(plan)

        return template.agenda

    def _register_plan_events(self, plan: "SessionPlan") -> None:  # type: ignore[name-defined]
        """Populate ``_event_handlers`` and ``_event_sources`` from the plan.

        Called by :meth:`_resolve_plan_agenda` after a plan is successfully
        loaded.  Sources are instantiated via :func:`~nardial.events.specs.instantiate_source`
        so that ``SessionManager`` only stores ready-to-run ``EventSource``
        objects, never raw spec dicts.

        Parameters
        ----------
        plan : SessionPlan
            The loaded plan whose ``event_handlers`` and ``event_sources``
            fields should be registered.
        """
        from nardial.events.specs import instantiate_source

        for spec in plan.event_handlers:
            self._event_handlers[spec.event_type] = spec
            logger.debug(
                "Registered event handler: event_type=%r → dialog %r",
                spec.event_type, spec.handler_dialog_id,
            )

        for source_spec in plan.event_sources:
            source = instantiate_source(source_spec)
            self._event_sources.append(source)
            logger.debug("Registered event source: %r", source.source_id)

    # ── Public event registration ─────────────────────────────────────────────

    def add_event_source(self, source: "EventSource") -> "SessionManager":
        """Register an additional :class:`~nardial.events.source.EventSource`.

        Returns ``self`` so calls can be chained::

            sm.add_event_source(TimerSource(...)).add_event_source(WebhookSource(...))

        The source is started by ``run_async()`` (Phase 8) as an asyncio task.

        Parameters
        ----------
        source : EventSource
            A fully configured source instance.

        Returns
        -------
        SessionManager
        """
        self._event_sources.append(source)
        logger.debug("Registered event source: %s", source.source_id)
        return self

    def add_event_handler(self, spec: "EventHandlerSpec") -> "SessionManager":
        """Register an event handler spec, keyed by ``spec.event_type``.

        A later call with the same ``event_type`` overwrites the earlier one.
        Returns ``self`` for chaining.

        Parameters
        ----------
        spec : EventHandlerSpec
            The handler mapping to register.

        Returns
        -------
        SessionManager
        """
        self._event_handlers[spec.event_type] = spec
        logger.debug(
            "Registered event handler: event_type=%r → dialog=%r",
            spec.event_type, spec.handler_dialog_id,
        )
        return self

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
        # Restore the incomplete session into the in-memory sessions list so
        # run() can call add_dialog_id() against the same session record.
        if not any(s.session_id == incomplete.session_id
                   for s in self.conversation_state.sessions):
            self.conversation_state.sessions.append(incomplete)
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

    def run(self) -> None:
        """Execute the session synchronously.

        Delegates to :meth:`run_async` via ``asyncio.run()``, which creates an
        ``EventBus``, starts registered event sources as asyncio tasks, and runs
        the dialog loop.  Callers that already manage an event loop should call
        ``run_async()`` directly and ``await`` it.
        """
        asyncio.run(self.run_async())

    async def run_async(self) -> None:
        """Execute the session asynchronously.

        Creates a fresh :class:`~nardial.events.bus.EventBus`, optionally adds
        sources from the device adapter, and runs all source tasks concurrently
        with the dialog loop.  When the dialog loop finishes the source tasks are
        cancelled and the bus is shut down.

        Call this directly (with ``await``) when you are already running inside
        an asyncio event loop (e.g. in an integration test or a larger async
        application).
        """
        self._bus = EventBus()
        # set_loop must happen before any source task starts so that emit_sync()
        # calls from callback threads (e.g. robot SDK) have a valid loop reference.
        self._bus.set_loop(asyncio.get_running_loop())

        # Wire the EventBus into the screen provider if it supports it.
        # SICScreenAdapter has set_event_bus(); NullScreenProvider does not —
        # hasattr guards the call so only adapters that opt in are wired.
        try:
            sp = self.agent.orchestrator.screen_provider
            if sp is not None and hasattr(sp, "set_event_bus"):
                sp.set_event_bus(self._bus)
                logger.debug("Wired EventBus to screen provider %r", type(sp).__name__)
        except AttributeError:
            # agent.orchestrator not present (e.g. partial mocks in tests) — skip silently.
            pass

        # Add any sources provided by the device adapter.
        try:
            device = self.agent.orchestrator.device
            for src in device.get_event_sources():
                self._event_sources.append(src)
        except (AttributeError, TypeError):
            # agent does not expose orchestrator/device, or get_event_sources()
            # returned a non-iterable (e.g. a stub or Mock in tests) — skip silently.
            pass

        source_tasks = [
            asyncio.create_task(src.run(self._bus), name=src.source_id)
            for src in self._event_sources
        ]
        try:
            await self._dialog_loop()
        finally:
            for task in source_tasks:
                task.cancel()
            if source_tasks:
                await asyncio.gather(*source_tasks, return_exceptions=True)
            self._bus.shutdown()

    async def _dialog_loop(self) -> None:
        """Core session loop: resolve the agenda and run each dialog in turn.

        For each dialog:

        1. BETWEEN_DIALOGS events are drained from the bus and the highest-priority
           handler dialog is run (if any).
        2. A final eligibility gate is applied (defense-in-depth).
        3. The dialog runs via :class:`~nardial.dialog_runtime.DialogRuntime`.
        4. If a BETWEEN_MOVES interrupt returned a checkpoint, the handler dialog
           (if any) is run, then the same dialog is queued for replay (``PAUSE``)
           or abandoned (``DISCARD``).
        5. On normal completion, both the in-session context and the persistent
           conversation state are updated.

        Session history and topics are persisted after the loop.
        """
        from nardial.dialog_runtime import _pick_dominant

        # Yield once so that source tasks scheduled by run_async() get a chance
        # to start before the dialog loop (potentially empty) returns.
        await asyncio.sleep(0)

        run_context = RunContext(
            session_history=[],
            topics_of_interest=self.conversation_state.topics_of_interest,
            user_model=self.conversation_state.user_model,
        )
        context = self._build_agenda_context()
        runtime = DialogRuntime(self.agent, event_bus=self._bus)

        checkpoint: "AnyCheckpoint | None" = None
        # When non-None, the dialog loop replays this dialog (PAUSE resume)
        # without advancing the agenda generator.
        pending_dialog = None

        gen = iter(resolve_agenda(self.session_agenda, context))

        while True:
            if pending_dialog is not None:
                dialog = pending_dialog
                pending_dialog = None
            else:
                dialog = next(gen, None)
                if dialog is None:
                    break

                # Eligibility gate — only for freshly yielded dialogs; a dialog
                # being replayed after PAUSE is inherently eligible.
                if not type(dialog).DEFAULT_ELIGIBILITY.is_eligible(dialog, context):
                    logger.debug("Skipped %s (final eligibility gate failed)", dialog.dialog_id)
                    continue

                # Record the dialog as started (only once, not on resume).
                self.conversation_state.add_dialog_id(self.session_id, dialog.dialog_id)
                run_context.session_history.append({
                    "role": "system",
                    "type": "dialog_start",
                    "dialog_id": dialog.dialog_id,
                })

            # Drain BETWEEN_DIALOGS events before each dialog (including resumptions).
            bd_events = await self._bus.drain_at_level(InterruptLevel.BETWEEN_DIALOGS)
            if bd_events:
                dominant = _pick_dominant(bd_events)
                if dominant is not None:
                    await self._run_handler_dialog(dominant, runtime, run_context, context)

            # Run the dialog as a watched task so the immediate-interrupt watchdog
            # can cancel it mid-execution when an IMMEDIATE event arrives.
            self._last_immediate_event = None
            dialog_task = asyncio.create_task(
                runtime.run(dialog, run_context, resume_from=checkpoint),
                name=f"dialog:{dialog.dialog_id}",
            )
            watchdog_task = asyncio.create_task(
                self._immediate_watchdog(dialog_task),
                name="immediate_watchdog",
            )
            try:
                returned = await dialog_task
            except asyncio.CancelledError:
                # Determine whether the watchdog or an outer cancellation fired.
                # The watchdog sets _last_immediate_event and returns (so its task
                # is done) BEFORE the CancelledError reaches this except block,
                # making watchdog_task.done() a reliable discriminator.
                if self._last_immediate_event is None or not watchdog_task.done():
                    # Outer session cancellation — propagate after cleaning up.
                    watchdog_task.cancel()
                    raise
                # Watchdog-triggered immediate interrupt.
                ev = self._last_immediate_event
                self._last_immediate_event = None
                logger.info(
                    "Dialog %r immediately interrupted by event %r",
                    dialog.dialog_id, ev.type,
                )
                run_context.session_history.append({
                    "role": "system",
                    "type": "dialog_interrupted",
                    "dialog_id": dialog.dialog_id,
                    "event_type": ev.type,
                    "resume_policy": ev.resume_policy.value,
                    "move_index": runtime._current_move_index,
                })
                await self._run_handler_dialog(ev, runtime, run_context, context)
                if ev.resume_policy == ResumePolicy.PAUSE:
                    from nardial.events.checkpoint import ScriptedMiniDialogCheckpoint
                    checkpoint = ScriptedMiniDialogCheckpoint(
                        dialog_id=dialog.dialog_id,
                        move_index=runtime._current_move_index,
                        current_outcome=run_context.current_outcome,
                    )
                    pending_dialog = dialog
                else:
                    checkpoint = None
                continue
            finally:
                watchdog_task.cancel()
                await asyncio.gather(watchdog_task, return_exceptions=True)

            checkpoint = None

            if returned is not None:
                # A BETWEEN_MOVES event interrupted the dialog mid-run.
                event: "Event | None" = runtime.last_interrupt_event
                runtime.last_interrupt_event = None
                if event is not None and event.handler_dialog_id:
                    await self._run_handler_dialog(event, runtime, run_context, context)
                if event is not None and event.resume_policy == ResumePolicy.PAUSE:
                    # Re-run the same dialog starting from the saved move_index.
                    checkpoint = returned
                    pending_dialog = dialog
                # Whether PAUSE or DISCARD, do not mark the dialog as completed.
                continue

            # Normal completion.
            run_context.session_history.append({
                "role": "system",
                "type": "dialog_end",
                "dialog_id": dialog.dialog_id,
            })
            if dialog.dialog_id not in self.conversation_state.completed_dialogs:
                self.conversation_state.completed_dialogs.append(dialog.dialog_id)
            context.mark_completed(dialog.dialog_id)

        logger.debug("Session history:\n%s", json.dumps(run_context.session_history, indent=2))
        logger.debug("Topics of interest: %s", run_context.topics_of_interest)

        topics_of_interest = await self.condense_topics(run_context.topics_of_interest)

        self.conversation_state.add_events(self.session_id, run_context.session_history)
        self.conversation_state.end_session(
            self.session_id,
            completed_ids=self.conversation_state.completed_dialogs,
            user_model=self.conversation_state.user_model,
            topics_of_interest=topics_of_interest,
        )
        self.conversation_state.save()

    async def _immediate_watchdog(self, dialog_task: asyncio.Task) -> None:
        """Poll the bus every 50 ms for IMMEDIATE events and cancel *dialog_task* on detection.

        Runs as a sibling ``asyncio.Task`` alongside the dialog task in
        :meth:`_dialog_loop`.  Exits when:

        - *dialog_task* completes normally (loop exits cleanly), or
        - an IMMEDIATE event is detected (stores it on ``_last_immediate_event``
          and cancels *dialog_task* before returning).

        The 50 ms poll interval is a deliberate balance between responsiveness
        (< 100 ms is imperceptible) and CPU overhead.  At 50 ms the watchdog
        adds at most ~20 context switches per second to the event loop.

        Parameters
        ----------
        dialog_task : asyncio.Task
            The running dialog task to watch.
        """
        while not dialog_task.done():
            await asyncio.sleep(_WATCHDOG_POLL_INTERVAL)
            if dialog_task.done():
                break
            try:
                ev = await self._bus.get_immediate()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.critical(
                    "Preemptive watchdog: unexpected error polling bus — watchdog disabled",
                    exc_info=True,
                )
                return
            if ev is not None:
                logger.debug(
                    "Immediate watchdog: IMMEDIATE event %r detected — cancelling dialog task",
                    ev.type,
                )
                self._last_immediate_event = ev
                dialog_task.cancel()
                return

    async def _run_handler_dialog(
        self,
        event: "Event",
        runtime: "DialogRuntime",
        run_context: RunContext,
        context: "AgendaContext",
    ) -> None:
        """Run the handler dialog declared for *event*, if any.

        The handler dialog ID is resolved by checking (in order):

        1. The ``handler_dialog_id`` field on the event itself.
        2. The ``_event_handlers`` registry keyed by ``event.type``.

        If the dialog is not found in the registry, a warning is logged and the
        method returns without error — a missing handler dialog is non-fatal.

        Parameters
        ----------
        event : Event
            The event that triggered this handler call.
        runtime : DialogRuntime
            The shared runtime instance to use for the handler dialog.
        run_context : RunContext
            The shared session context (history, user model, topics).
        context : AgendaContext
            The in-session eligibility context (updated after the handler runs).
        """
        # Prefer the event's explicit handler_dialog_id; fall back to the registry.
        dialog_id = event.handler_dialog_id
        if not dialog_id:
            handler_spec = self._event_handlers.get(event.type)
            if handler_spec:
                dialog_id = handler_spec.handler_dialog_id

        if not dialog_id:
            logger.debug(
                "Event %r has no handler dialog configured — skipping", event.type
            )
            return

        dialog = self._registry.get_by_id(dialog_id)
        if dialog is None:
            logger.warning(
                "Handler dialog %r for event %r not found in registry — skipping",
                dialog_id, event.type,
            )
            return

        logger.info("Running handler dialog %r for event %r", dialog_id, event.type)
        run_context.session_history.append({
            "role": "system",
            "type": "handler_dialog_start",
            "dialog_id": dialog_id,
            "event_type": event.type,
        })
        try:
            await runtime.run(dialog, run_context)
        finally:
            # Always close the history bracket so the transcript stays consistent
            # even if the handler dialog raises (e.g. a bug in a move handler).
            run_context.session_history.append({
                "role": "system",
                "type": "handler_dialog_end",
                "dialog_id": dialog_id,
            })

    async def condense_topics(self, topics_of_interest: list) -> list:
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
            result = await self.agent.extract_topics_with_llm(list(topics_of_interest))
            logger.debug("Condensed topics: %s", result)
            return result
        except Exception as e:
            logger.warning("Topic condensation failed: %s", e)
            return topics_of_interest
