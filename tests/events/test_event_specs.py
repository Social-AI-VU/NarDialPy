"""Tests for EventHandlerSpec, source specs, and instantiate_source."""

import pytest
from pydantic import ValidationError

from nardial.events import (
    BackgroundLLMSource,
    InterruptLevel,
    ResumePolicy,
    TimerSource,
    WebhookSource,
    instantiate_source,
)
from nardial.events.specs import (
    AnyEventSourceSpec,
    EventHandlerSpec,
    TimerSourceSpec,
    WebhookSourceSpec,
)


# ---------------------------------------------------------------------------
# EventHandlerSpec
# ---------------------------------------------------------------------------

def test_event_handler_spec_defaults():
    spec = EventHandlerSpec(event_type="button_press", handler_dialog_id="handle_btn")
    assert spec.interrupt_level == InterruptLevel.BETWEEN_DIALOGS
    assert spec.resume_policy == ResumePolicy.DISCARD
    assert spec.priority == 50
    assert spec.source_filter is None


def test_event_handler_spec_custom_fields():
    spec = EventHandlerSpec(
        event_type="timer_tick",
        handler_dialog_id="timer_dialog",
        interrupt_level=InterruptLevel.BETWEEN_MOVES,
        resume_policy=ResumePolicy.PAUSE,
        priority=10,
        source_filter="TimerSource(tick)",
    )
    assert spec.interrupt_level == InterruptLevel.BETWEEN_MOVES
    assert spec.resume_policy == ResumePolicy.PAUSE
    assert spec.priority == 10
    assert spec.source_filter == "TimerSource(tick)"


# ---------------------------------------------------------------------------
# TimerSourceSpec
# ---------------------------------------------------------------------------

def test_timer_source_spec_defaults():
    spec = TimerSourceSpec(event_type="tick", delay_seconds=5.0)
    assert spec.repeat is False
    assert spec.interrupt_level == InterruptLevel.BETWEEN_DIALOGS
    assert spec.resume_policy == ResumePolicy.DISCARD
    assert spec.handler_dialog_id is None
    assert spec.priority == 50


def test_timer_source_spec_validation_error_on_missing_required():
    with pytest.raises(ValidationError):
        TimerSourceSpec()  # event_type and delay_seconds are required


# ---------------------------------------------------------------------------
# WebhookSourceSpec
# ---------------------------------------------------------------------------

def test_webhook_source_spec_defaults():
    spec = WebhookSourceSpec()
    assert spec.host == "0.0.0.0"
    assert spec.port == 8765
    assert spec.default_interrupt_level == InterruptLevel.BETWEEN_DIALOGS
    assert spec.default_priority == 30


def test_webhook_source_spec_custom():
    spec = WebhookSourceSpec(host="127.0.0.1", port=9000, default_priority=5)
    assert spec.host == "127.0.0.1"
    assert spec.port == 9000
    assert spec.default_priority == 5


# ---------------------------------------------------------------------------
# Discriminated union parsing
# ---------------------------------------------------------------------------

def test_any_event_source_spec_parses_timer():
    from pydantic import TypeAdapter
    adapter = TypeAdapter(AnyEventSourceSpec)
    spec = adapter.validate_python({"type": "timer", "event_type": "tick", "delay_seconds": 3.0})
    assert isinstance(spec, TimerSourceSpec)
    assert spec.delay_seconds == 3.0


def test_any_event_source_spec_parses_webhook():
    from pydantic import TypeAdapter
    adapter = TypeAdapter(AnyEventSourceSpec)
    spec = adapter.validate_python({"type": "webhook", "port": 9000})
    assert isinstance(spec, WebhookSourceSpec)
    assert spec.port == 9000


def test_any_event_source_spec_rejects_unknown_type():
    from pydantic import TypeAdapter
    adapter = TypeAdapter(AnyEventSourceSpec)
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "unknown_source"})


# ---------------------------------------------------------------------------
# instantiate_source factory
# ---------------------------------------------------------------------------

def test_instantiate_source_creates_timer_source():
    spec = TimerSourceSpec(event_type="tick", delay_seconds=1.0, repeat=True, priority=20)
    source = instantiate_source(spec)
    assert isinstance(source, TimerSource)
    assert source._event_type == "tick"
    assert source._delay == 1.0
    assert source._repeat is True
    assert source._priority == 20


def test_instantiate_source_creates_webhook_source():
    spec = WebhookSourceSpec(host="127.0.0.1", port=8888)
    source = instantiate_source(spec)
    assert isinstance(source, WebhookSource)
    assert source._host == "127.0.0.1"
    assert source._port == 8888
