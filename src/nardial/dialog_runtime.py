"""Dialog execution runtime — shared types, helpers, and the async execution engine.

This module is the single home of everything that belongs to *running* a dialog
rather than *defining* one.  Dialog classes (MiniDialog, LLMDialog, …) import
types from here; this module has no reverse dependency on mini_dialogs.

Public API
----------
RunContext           Mutable state accumulated during a single dialog execution.
DialogType           Canonical dialog category enum.
MAX_LLM_TURNS        Default turn budget for LLM conversations.
extract_open_value   Heuristic cleaner for open-ended user answers.
DialogRuntime        Async execution engine — the sole entry point for running dialogs.

Internal (used by tests)
------------------------
_run_llm_exchange    Async multi-turn LLM conversation driver (exposed for direct testing).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import TYPE_CHECKING, Any

from nardial.moves import (
    MOVE_ANIMATION,
    MOVE_ANSWER_LLM,
    MOVE_ANSWER_OPEN,
    MOVE_ANSWER_OPTIONS,
    MOVE_ANSWER_YESNO,
    MOVE_ASK_LLM,
    MOVE_ASK_OPEN,
    MOVE_ASK_OPTIONS,
    MOVE_ASK_YESNO,
    MOVE_LLM_FOLLOWUP,
    MOVE_MOTION_SEQUENCE,
    MOVE_PLAY_AUDIO,
    MOVE_SAY,
    MOVE_TIMED_WAIT,
    MOVE_WAIT_FOR_BUTTON,
    MOVE_WAIT_FOR_WEB_INPUT,
)

if TYPE_CHECKING:
    from nardial.events.bus import EventBus
    from nardial.events.checkpoint import AnyCheckpoint

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

@dataclass
class RunContext:
    """Mutable conversational state accumulated during a single dialog execution.

    The agent (ConversationAgent) is intentionally kept separate — it is a
    stable capability provider, not state.  Only data that changes *as the
    dialog runs* belongs here: the growing history, the user model, discovered
    topics, and the outcome of the most recent ask-move.
    """

    session_history: list[dict[str, Any]] = field(default_factory=list)
    topics_of_interest: list[str] = field(default_factory=list)
    user_model: Any = field(default_factory=dict)  # UserModel or plain dict
    current_outcome: str | None = None


# ---------------------------------------------------------------------------
# Dialog categorisation
# ---------------------------------------------------------------------------

class DialogType(Enum):
    NARRATIVE  = "narrative"
    CHITCHAT   = "chitchat"
    FUNCTIONAL = "functional"
    LLM_BASED  = "llm_based"


# ---------------------------------------------------------------------------
# LLM conversation constants
# ---------------------------------------------------------------------------

MAX_LLM_TURNS = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_open_value(answer: str) -> str:
    """Heuristic cleaner for open answers used with ``set_variable``.

    Resolution order (language-agnostic):
    1. If quoted text is present, return the first quoted segment.
    2. Otherwise, return the last alphabetic token (e.g., ``'zebra'`` from
       ``'my favorite animal is a zebra'``).
    3. Fallback: return the trimmed original answer.
    """
    if not answer:
        return ""
    text = str(answer).strip()
    m = re.search(r'["\']([^"\']+)["\']', text)
    if m:
        return m.group(1).strip()
    tokens = re.findall(r"[A-Za-z][A-Za-z\-']+", text)
    if tokens:
        return tokens[-1]
    return text


def _substitute_variables(text: str, user_model: Any) -> str:
    """Replace ``%variable%`` placeholders in ``text`` with values from ``user_model``."""
    for var, value in user_model.items():
        text = text.replace(f"%{var}%", str(value))
    return text


async def _run_llm_exchange(
    agent: Any,
    context: RunContext,
    prompt: str,
    max_turns: int,
    set_variable: str | None = None,
    quit_phrases: list[str] | None = None,
    quit_signal: str | None = None,
    speak_first: bool = True,
    duration: float | None = None,
    rag_enabled: bool = False,
    index_name: str | None = None,
    *,
    resume_history: list[str] | None = None,
    resume_turn_index: int = 0,
    resume_user_input: str = "",
    resume_elapsed: float = 0.0,
) -> None:
    """Drive an async multi-turn LLM conversation loop.

    Parameters
    ----------
    agent : ConversationAgent
        Provides async ``ask_llm``, ``say``, and ``orchestrator.listen``.
    context : RunContext
        Accumulates session history and user model updates.
    prompt : str
        System prompt passed to the LLM on every turn.
    max_turns : int
        Maximum number of LLM turns to execute.
    set_variable : str, optional
        Store the last user answer in ``context.user_model`` under this key.
    quit_phrases : list of str, optional
        User utterances that stop the loop early.
    quit_signal : str, optional
        Token the LLM embeds to signal end of conversation.
    speak_first : bool
        If False, listen for the user's opening utterance before the first LLM call.
    duration : float, optional
        Total wall-clock time budget in seconds; the loop stops when time runs out.
    rag_enabled : bool
        Whether to enable retrieval-augmented generation.
    index_name : str, optional
        Vector store index name for RAG queries.
    resume_history : list of str, optional
        Accumulated dialog history from a previous run (used when resuming).
    resume_turn_index : int
        Turn to start from when resuming (default 0 = start fresh).
    resume_user_input : str
        Last user input from the previous run, used as the opening prompt on resume.
    resume_elapsed : float
        Seconds already elapsed in a previous run; subtracted from the duration budget.
    """
    dialog_history: list[str] = list(resume_history) if resume_history else []
    user_input = resume_user_input
    start_time = monotonic() - resume_elapsed

    def remaining_time() -> float | None:
        if duration is None:
            return None
        return max(0.0, duration - (monotonic() - start_time))

    if not speak_first:
        timeout = remaining_time()
        if timeout is not None and timeout <= 0:
            return
        result = await agent.orchestrator.listen(timeout=timeout or 10)
        user_input = result.transcript or ""
        context.session_history.append({"role": "user", "type": MOVE_ANSWER_LLM, "text": user_input})

    for _ in range(resume_turn_index, max_turns or MAX_LLM_TURNS):
        timeout = remaining_time()
        if timeout is not None and timeout <= 0:
            return
        llm_text = await agent.ask_llm(
            user_prompt=user_input,
            context_messages=dialog_history,
            system_prompt=prompt,
            rag_enabled=rag_enabled,
            index_name=index_name,
        )
        if llm_text is None:
            continue

        # If the LLM embeds a quit signal, speak any remaining content and stop.
        if quit_signal and quit_signal in llm_text:
            clean = llm_text.replace(quit_signal, "").strip()
            if clean:
                await agent.say(clean)
                context.session_history.append({"role": "robot", "type": MOVE_SAY, "text": clean})
            return

        # Ask the user the LLM's text and listen for reply.
        await agent.say(llm_text)
        timeout = remaining_time()
        if timeout is not None and timeout <= 0:
            return
        result = await agent.orchestrator.listen(timeout=timeout or 10)
        user_input = result.transcript or ""

        # Record the exchange.
        context.session_history.append({"role": "robot", "type": MOVE_ASK_LLM, "text": llm_text})
        context.session_history.append({"role": "user", "type": MOVE_ANSWER_LLM, "text": user_input})

        # Optionally store a variable from the user's answer.
        if set_variable and user_input:
            context.user_model[set_variable] = extract_open_value(user_input)

        # Stop early if the user said a configured quit phrase.
        if any(qp and qp.lower() in user_input.lower() for qp in (quit_phrases or [])):
            return

        dialog_history.append(user_input)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pick_dominant(events: list) -> Any | None:
    """Return the highest-priority event (lowest priority value, then lowest seq).

    Used by both :class:`DialogRuntime` and ``SessionManager`` to select the
    most important event from a batch drained from the bus.
    """
    if not events:
        return None
    return min(events, key=lambda e: (e.priority, e.seq))


# ---------------------------------------------------------------------------
# Execution engine
# ---------------------------------------------------------------------------

class DialogRuntime:
    """Async execution engine for all dialog types.

    Owns move dispatch, variable substitution, session-history recording, and
    (from Phase 8 onwards) event-bus checkpointing.  After Phase 5, dialogs
    (``MiniDialog``, ``LLMDialog``) are pure data containers — they carry no
    handler methods.  All execution logic lives here.

    Parameters
    ----------
    agent : ConversationAgent
        Async capability provider for speech, listening, and LLM calls.
    event_bus : EventBus, optional
        Shared event bus for between-moves / preemptive interrupt handling.
        ``None`` until Phase 8; the runtime runs without event support.
    """

    def __init__(self, agent: Any, event_bus: "EventBus | None" = None) -> None:
        self._agent = agent
        self._bus = event_bus
        # Set by _run_mini when a BETWEEN_MOVES event interrupts a dialog;
        # read by SessionManager._dialog_loop() to decide PAUSE vs DISCARD.
        self.last_interrupt_event: Any = None
        # Updated by _run_mini before each move dispatch; used by the preemptive
        # watchdog to build a best-effort checkpoint when the dialog task is cancelled.
        self._current_move_index: int = 0

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        dialog: Any,
        context: RunContext,
        *,
        resume_from: "AnyCheckpoint | None" = None,
    ) -> "AnyCheckpoint | None":
        """Execute ``dialog`` using ``context`` and return a checkpoint if interrupted.

        Parameters
        ----------
        dialog : BaseDialog
            The dialog to execute (``MiniDialog`` or ``LLMDialog`` instance).
        context : RunContext
            Mutable conversational state for this execution.
        resume_from : AnyCheckpoint, optional
            Checkpoint from a prior interrupted run; resumes from that point.

        Returns
        -------
        AnyCheckpoint or None
            A checkpoint if the dialog was interrupted with PAUSE policy, else None.

        Raises
        ------
        TypeError
            If ``dialog`` is not a recognised dialog type.
        """
        # Import here to avoid circular imports at module load time.
        from nardial.mini_dialogs import LLMDialog, MiniDialog

        if isinstance(dialog, LLMDialog):
            return await self._run_llm(dialog, context, resume_from)
        if isinstance(dialog, MiniDialog):
            return await self._run_mini(dialog, context, resume_from)
        raise TypeError(f"No runtime handler for {type(dialog).__name__}")

    # ------------------------------------------------------------------
    # MiniDialog execution
    # ------------------------------------------------------------------

    async def _run_mini(
        self, dialog: Any, context: RunContext, resume_from: "AnyCheckpoint | None"
    ) -> "AnyCheckpoint | None":
        """Execute a scripted dialog, optionally resuming from a checkpoint.

        Between each move, the event bus is polled for ``BETWEEN_MOVES`` events.
        If one is found the dominant event is stored in :attr:`last_interrupt_event`
        and the method returns:

        - A :class:`~nardial.events.checkpoint.MiniDialogCheckpoint` (``PAUSE``
          resume policy) so ``SessionManager`` can replay the dialog from the
          interrupted move after running the handler dialog.
        - ``None`` (``DISCARD`` resume policy) to abandon the dialog silently.
        """
        from nardial.events.checkpoint import MiniDialogCheckpoint
        from nardial.events.types import InterruptLevel, ResumePolicy

        start_index = resume_from.move_index if isinstance(resume_from, MiniDialogCheckpoint) else 0
        if resume_from:
            context.current_outcome = resume_from.current_outcome

        for i, move in enumerate(dialog.moves):
            if i < start_index:
                continue

            # Check for a between-moves interrupt before each move.
            if self._bus is not None and self._bus.has_pending(InterruptLevel.BETWEEN_MOVES):
                events = await self._bus.drain_at_level(InterruptLevel.BETWEEN_MOVES)
                dominant = _pick_dominant(events)
                if dominant is not None:
                    self.last_interrupt_event = dominant
                    if dominant.resume_policy == ResumePolicy.PAUSE:
                        return MiniDialogCheckpoint(
                            dialog_id=dialog.dialog_id,
                            move_index=i,
                            current_outcome=context.current_outcome,
                        )
                    return None  # DISCARD: abandon dialog, no checkpoint

            # Record the move index before dispatching so the preemptive watchdog
            # can read it as a best-effort resume point if the task is cancelled.
            self._current_move_index = i
            await self._dispatch_move(move, context)
        return None

    async def _dispatch_move(self, move: Any, context: RunContext) -> None:
        """Route a move to its async handler by naming convention: ``_handle_<move.type>``.

        Unknown move types are logged and skipped.
        """
        handler = getattr(self, f"_handle_{move.type}", None)
        if handler is None:
            logger.warning("DialogRuntime: no handler for move type %r — move skipped", move.type)
        else:
            await handler(move, context)

    # ------------------------------------------------------------------
    # LLMDialog execution
    # ------------------------------------------------------------------

    async def _run_llm(
        self, dialog: Any, context: RunContext, resume_from: "AnyCheckpoint | None"
    ) -> "AnyCheckpoint | None":
        """Execute a free-form LLM dialog, optionally resuming from a checkpoint.

        When *resume_from* is an :class:`~nardial.events.checkpoint.LLMDialogCheckpoint`,
        the accumulated conversation history, turn counter, last user input, and
        elapsed time are restored so the exchange continues where it left off.
        """
        from nardial.events.checkpoint import LLMDialogCheckpoint

        resume_history: list[str] = []
        resume_turn_index = 0
        resume_user_input = ""
        resume_elapsed = 0.0
        if isinstance(resume_from, LLMDialogCheckpoint):
            resume_elapsed = resume_from.elapsed_seconds
            resume_history = list(resume_from.dialog_history)
            resume_turn_index = resume_from.turn_index
            resume_user_input = resume_from.last_user_input

        await _run_llm_exchange(
            agent=self._agent,
            context=context,
            prompt=dialog.prompt,
            max_turns=dialog.max_turns or MAX_LLM_TURNS,
            set_variable=None,
            quit_phrases=dialog.quit_phrases,
            quit_signal=dialog.quit_signal,
            speak_first=dialog.speak_first,
            duration=dialog.duration,
            rag_enabled=dialog.rag_enabled,
            index_name=dialog.index_name,
            resume_history=resume_history,
            resume_turn_index=resume_turn_index,
            resume_user_input=resume_user_input,
            resume_elapsed=resume_elapsed,
        )
        return None

    # ------------------------------------------------------------------
    # Shared internal helpers
    # ------------------------------------------------------------------

    def _resolve_outcome(self, move: Any, answer: str | None, context: RunContext) -> None:
        """Resolve and store ``context.current_outcome`` from the move's outcome fields.

        Resolution order:
        1. Exact match in ``outcomes``.
        2. Wildcard ``"*"`` if answer is non-empty.
        3. ``default_outcome`` when no match or answer is empty/None.
        """
        outcomes = move.outcomes
        if answer and answer in outcomes:
            context.current_outcome = outcomes[answer]
        elif answer and "*" in outcomes:
            context.current_outcome = outcomes["*"]
        else:
            context.current_outcome = move.default_outcome

    def _store_set_variable(self, move: Any, answer: str, context: RunContext) -> None:
        """Store the extracted answer in ``context.user_model`` if the move declares ``set_variable``."""
        if not answer:
            return
        if getattr(move, "set_variable", None):
            context.user_model[move.set_variable] = extract_open_value(answer)

    def _store_interests(self, move: Any, answer: str, context: RunContext) -> None:
        """Append interest topics derived from the answer or a user model variable."""
        from nardial.mini_dialogs import MiniDialog
        if answer and getattr(move, "add_interest_from_answer", False):
            MiniDialog.add_interest(context.topics_of_interest, answer)
        if getattr(move, "add_interest_from_variable", None):
            val = context.user_model.get(move.add_interest_from_variable)
            if val:
                MiniDialog.add_interest(context.topics_of_interest, val)

    async def _generate_llm_followup(
        self, context: RunContext, user_answer: str, system_prompt: str
    ) -> None:
        """Ask the LLM to generate a follow-up response and speak it."""
        context_messages = [
            entry.get("text", "") for entry in context.session_history
            if entry.get("text") is not None
        ]
        llm_text = await self._agent.ask_llm(
            user_prompt=user_answer,
            context_messages=context_messages,
            system_prompt=system_prompt,
        )
        if llm_text:
            await self._agent.say(llm_text)
            context.session_history.append(
                {"role": "robot", "type": MOVE_LLM_FOLLOWUP, "text": llm_text}
            )

    async def _finalize_ask(self, move: Any, answer: str | None, context: RunContext) -> None:
        """Shared tail for all ask-move handlers: variable storage, interests, LLM followup, outcome."""
        logger.debug("User answered: %s", answer)
        self._store_set_variable(move, answer, context)
        self._store_interests(move, answer, context)
        if move.llm_followup:
            await self._generate_llm_followup(
                context, user_answer=answer or "", system_prompt=move.llm_followup
            )
        self._resolve_outcome(move, answer, context)

    # ------------------------------------------------------------------
    # Move handlers
    # ------------------------------------------------------------------

    async def _handle_branch(self, move: Any, context: RunContext) -> None:
        """Execute sub-moves for the case matching the current outcome or user model key."""
        key = context.current_outcome if move.on == "outcome" else context.user_model.get(move.on)
        for sub_move in move.cases.get(key, []):
            await self._dispatch_move(sub_move, context)

    async def _handle_say(self, move: Any, context: RunContext) -> None:
        text = _substitute_variables(move.text, context.user_model)
        await self._agent.say(text)
        context.session_history.append({"role": "robot", "type": MOVE_SAY, "text": text})

    async def _handle_ask_yesno(self, move: Any, context: RunContext) -> None:
        """Ask a yes/no question, record the exchange, handle side-effects, and resolve the outcome."""
        from nardial.mini_dialogs import MiniDialog
        text = _substitute_variables(move.text, context.user_model)
        answer = await self._agent.ask_yesno(text)
        context.session_history.append({"role": "robot", "type": MOVE_ASK_YESNO, "text": text})
        context.session_history.append({"role": "user", "type": MOVE_ANSWER_YESNO, "text": answer})
        if answer == "yes" and move.add_interest:
            MiniDialog.add_interest(context.topics_of_interest, move.add_interest)
        await self._finalize_ask(move, answer, context)

    async def _handle_ask_open(self, move: Any, context: RunContext) -> None:
        """Ask an open-ended question, record the exchange, handle side-effects, and resolve the outcome."""
        text = _substitute_variables(move.text, context.user_model)
        answer = await self._agent.ask_open(text)
        context.session_history.append({"role": "robot", "type": MOVE_ASK_OPEN, "text": text})
        context.session_history.append({"role": "user", "type": MOVE_ANSWER_OPEN, "text": answer})
        await self._finalize_ask(move, answer, context)

    async def _handle_ask_options(self, move: Any, context: RunContext) -> None:
        """Ask a multiple-choice question, record the exchange, handle side-effects, and resolve the outcome."""
        text = _substitute_variables(move.text, context.user_model)
        answer = await self._agent.ask_options(text, move.options)
        context.session_history.append(
            {"role": "robot", "type": MOVE_ASK_OPTIONS, "text": text, "options": move.options}
        )
        context.session_history.append({"role": "user", "type": MOVE_ANSWER_OPTIONS, "text": answer})
        await self._finalize_ask(move, answer, context)

    async def _handle_play_audio(self, move: Any, context: RunContext) -> None:
        self._agent.play_audio(move.audio)
        context.session_history.append(
            {"role": "robot", "type": MOVE_PLAY_AUDIO, "text": "Played audio.", "audio_file": move.audio}
        )

    async def _handle_motion_sequence(self, move: Any, context: RunContext) -> None:
        self._agent.play_motion_sequence(move.motion_sequence)
        context.session_history.append(
            {"role": "robot", "type": MOVE_MOTION_SEQUENCE,
             "text": "Played motion sequence.", "motion_sequence_file": move.motion_sequence}
        )

    async def _handle_animation(self, move: Any, context: RunContext) -> None:
        self._agent.play_animation(move.animation_name)
        context.session_history.append(
            {"role": "robot", "type": MOVE_ANIMATION,
             "text": "Played animation.", "animation_name": move.animation_name}
        )

    async def _handle_ask_llm(self, move: Any, context: RunContext) -> None:
        await _run_llm_exchange(
            agent=self._agent,
            context=context,
            prompt=move.prompt,
            max_turns=move.max_turns or MAX_LLM_TURNS,
            set_variable=move.set_variable,
            quit_phrases=move.quit_phrases,
            quit_signal=move.quit_signal,
        )

    async def _handle_wait_for_button(self, move: Any, context: RunContext) -> None:
        """Wait for a button-press event from the event bus or until timeout.

        If no event bus is wired up, resolves immediately to ``move.default_outcome``
        so dialogs can be tested without live hardware.
        """
        if self._bus is None:
            logger.warning(
                "wait_for_button move encountered but no EventBus is attached — "
                "resolving to default_outcome=%r", move.default_outcome
            )
            context.current_outcome = move.default_outcome
            return

        def _predicate(ev: Any) -> bool:
            return ev.type == "button_press" and ev.source in move.buttons

        sub = self._bus.subscribe(_predicate)
        try:
            ev = await asyncio.wait_for(sub.get(), timeout=move.timeout)
            context.current_outcome = move.outcomes.get(ev.source, move.default_outcome)
            context.session_history.append({
                "role": "system",
                "type": MOVE_WAIT_FOR_BUTTON,
                "outcome": context.current_outcome,
                "source": ev.source,
            })
        except asyncio.TimeoutError:
            context.current_outcome = move.default_outcome
            logger.debug(
                "wait_for_button timed out after %ss; resolving to %r",
                move.timeout, move.default_outcome,
            )
            context.session_history.append({
                "role": "system",
                "type": MOVE_WAIT_FOR_BUTTON,
                "outcome": context.current_outcome,
                "source": None,
            })
        finally:
            self._bus.unsubscribe(sub)

    async def _handle_timed_wait(self, move: Any, context: RunContext) -> None:
        """Sleep for a fixed duration before continuing to the next move."""
        await asyncio.sleep(move.duration_seconds)
        context.session_history.append({
            "role": "system",
            "type": MOVE_TIMED_WAIT,
            "duration_seconds": move.duration_seconds,
        })

    async def _handle_wait_for_web_input(self, move: Any, context: RunContext) -> None:
        """Wait for a web-input event whose value is in ``move.options``, or until timeout.

        If no event bus is wired up, resolves immediately to ``move.default_outcome``.
        """
        if self._bus is None:
            logger.warning(
                "wait_for_web_input move encountered but no EventBus is attached — "
                "resolving to default_outcome=%r", move.default_outcome
            )
            context.current_outcome = move.default_outcome
            return

        def _predicate(ev: Any) -> bool:
            return (
                ev.type == "web_input"
                and isinstance(ev.data, dict)
                and ev.data.get("value") in move.options
            )

        sub = self._bus.subscribe(_predicate)
        try:
            ev = await asyncio.wait_for(sub.get(), timeout=move.timeout)
            value = ev.data.get("value")
            context.current_outcome = move.outcomes.get(value, move.default_outcome)
            context.session_history.append({
                "role": "system",
                "type": MOVE_WAIT_FOR_WEB_INPUT,
                "outcome": context.current_outcome,
                "value": value,
            })
        except asyncio.TimeoutError:
            context.current_outcome = move.default_outcome
            logger.debug(
                "wait_for_web_input timed out after %ss; resolving to %r",
                move.timeout, move.default_outcome,
            )
            context.session_history.append({
                "role": "system",
                "type": MOVE_WAIT_FOR_WEB_INPUT,
                "outcome": context.current_outcome,
                "value": None,
            })
        finally:
            self._bus.unsubscribe(sub)
