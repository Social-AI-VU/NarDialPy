"""Pydantic models for declarative event configuration in session JSON files.

These models let dialog designers configure event sources and handlers inside
a ``SessionPlan`` JSON file without writing Python code.  The
``instantiate_source()`` factory converts a validated spec into a concrete
:class:`~nardial.events.source.EventSource` instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, Field

from nardial.events.types import InterruptLevel, ResumePolicy

if TYPE_CHECKING:
    from nardial.events.source import EventSource


class EventHandlerSpec(BaseModel):
    """Declares that a specific event type should trigger a handler dialog.

    Attributes
    ----------
    event_type : str
        The ``Event.type`` string that activates this handler.
    handler_dialog_id : str
        ID of the dialog to run when the event fires.
    interrupt_level : InterruptLevel
        When the handler dialog is inserted into the session flow.
    resume_policy : ResumePolicy
        What to do with the interrupted dialog after the handler finishes.
    priority : int
        Lower values are processed first when multiple handlers compete.
    source_filter : str or None
        If set, only events from a source with this ``source_id`` match.
    """

    event_type: str
    handler_dialog_id: str
    interrupt_level: InterruptLevel = InterruptLevel.BETWEEN_DIALOGS
    resume_policy: ResumePolicy = ResumePolicy.DISCARD
    priority: int = 50
    source_filter: str | None = None


class TimerSourceSpec(BaseModel):
    """Configuration for a :class:`~nardial.events.sources.timer.TimerSource`.

    Attributes
    ----------
    type : str
        Discriminator field; always ``"timer"``.
    event_type : str
        ``Event.type`` string emitted by the timer.
    delay_seconds : float
        Delay before the first (and, if ``repeat=False``, only) emission.
    repeat : bool
        If True, the timer re-arms automatically after each emission.
    interrupt_level : InterruptLevel
        Interrupt granularity for emitted events.
    resume_policy : ResumePolicy
        Resume policy for emitted events.
    handler_dialog_id : str or None
        Handler dialog to run when the timer fires.
    priority : int
        Event priority in the bus queue.
    """

    type: Literal["timer"] = "timer"
    event_type: str
    delay_seconds: float
    repeat: bool = False
    interrupt_level: InterruptLevel = InterruptLevel.BETWEEN_DIALOGS
    resume_policy: ResumePolicy = ResumePolicy.DISCARD
    handler_dialog_id: str | None = None
    priority: int = 50


class WebhookSourceSpec(BaseModel):
    """Configuration for a :class:`~nardial.events.sources.webhook.WebhookSource`.

    Attributes
    ----------
    type : str
        Discriminator field; always ``"webhook"``.
    host : str
        Network interface to bind.
    port : int
        TCP port to listen on.
    default_interrupt_level : InterruptLevel
        Applied to events that do not supply their own interrupt level.
    default_priority : int
        Applied to events that do not supply their own priority.
    """

    type: Literal["webhook"] = "webhook"
    host: str = "0.0.0.0"
    port: int = 8765
    default_interrupt_level: InterruptLevel = InterruptLevel.BETWEEN_DIALOGS
    default_priority: int = 30


#: Discriminated union of all declarative source spec types.
AnyEventSourceSpec = Annotated[
    TimerSourceSpec | WebhookSourceSpec,
    Field(discriminator="type"),
]


def instantiate_source(spec: AnyEventSourceSpec) -> "EventSource":
    """Create a concrete :class:`~nardial.events.source.EventSource` from a spec.

    Parameters
    ----------
    spec : AnyEventSourceSpec
        A validated source spec (``TimerSourceSpec`` or ``WebhookSourceSpec``).

    Returns
    -------
    EventSource
        The corresponding concrete source instance, ready to be passed to
        ``SessionManager.add_event_source()``.

    Raises
    ------
    ValueError
        If the spec type is not recognised.
    """
    # Deferred imports to avoid circular dependency during package init.
    from nardial.events.sources.timer import TimerSource
    from nardial.events.sources.webhook import WebhookSource

    if isinstance(spec, TimerSourceSpec):
        return TimerSource(
            event_type=spec.event_type,
            delay_seconds=spec.delay_seconds,
            repeat=spec.repeat,
            interrupt_level=spec.interrupt_level,
            resume_policy=spec.resume_policy,
            handler_dialog_id=spec.handler_dialog_id,
            priority=spec.priority,
        )
    if isinstance(spec, WebhookSourceSpec):
        return WebhookSource(
            host=spec.host,
            port=spec.port,
            default_interrupt_level=spec.default_interrupt_level,
            default_priority=spec.default_priority,
        )
    raise ValueError(f"Unknown event source spec type: {type(spec).__name__}")
