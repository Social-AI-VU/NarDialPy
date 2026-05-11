"""Tests for the ScreenProvider system.

Groups
------
1. NullScreenProvider — protocol conformance and callability
2. New move types — Pydantic validation
3. JSON parsing via AnyMove discriminator
4. New move handlers in DialogRuntime (with / without screen provider)
5. _handle_wait_for_web_input screen integration
6. Auto-push transcript from InteractionOrchestrator
7. SICScreenAdapter — EventBus wiring and button click handling
"""

import asyncio
import logging
import sys

import pytest
from pydantic import TypeAdapter, ValidationError
from unittest.mock import AsyncMock, MagicMock, patch

from nardial.dialog_runtime import DialogRuntime, RunContext
from nardial.events import EventBus
from nardial.events.types import Event, InterruptLevel, ResumePolicy
from nardial.interaction_orchestrator import InteractionOrchestrator
from nardial.moves import (
    AnyMove,
    MoveBlackScreen,
    MoveShowHtml,
    MoveShowIframe,
    MoveShowImage,
    MoveShowVideo,
    MoveWaitForWebInput,
    MOVE_BLACK_SCREEN,
    MOVE_SHOW_HTML,
    MOVE_SHOW_IFRAME,
    MOVE_SHOW_IMAGE,
    MOVE_SHOW_VIDEO,
)
from nardial.providers.screen import ScreenProvider
from nardial.providers.screen.null import NullScreenProvider
from nardial.providers.screen.sic_adapter import SICScreenAdapter


# ===========================================================================
# Group 1: NullScreenProvider — protocol conformance and callability
# ===========================================================================

def test_null_screen_satisfies_protocol():
    assert isinstance(NullScreenProvider(), ScreenProvider)


async def test_null_show_transcript():
    await NullScreenProvider().show_transcript("Hello from robot.")


async def test_null_show_user_transcript():
    await NullScreenProvider().show_user_transcript("Hello from user.")


async def test_null_show_image():
    await NullScreenProvider().show_image("images/welcome.jpg", caption="Welcome")


async def test_null_show_image_caption_optional():
    # Default caption="" must not raise.
    await NullScreenProvider().show_image("images/welcome.jpg")


async def test_null_show_video():
    await NullScreenProvider().show_video("videos/intro.mp4")


async def test_null_show_iframe():
    await NullScreenProvider().show_iframe("https://example.com")


async def test_null_show_html():
    await NullScreenProvider().show_html("<h1>Hello</h1>")


async def test_null_show_buttons():
    await NullScreenProvider().show_buttons(["Option A", "Option B"])


async def test_null_show_text_input():
    await NullScreenProvider().show_text_input(prompt="Type your answer")


async def test_null_hide_input():
    await NullScreenProvider().hide_input()


async def test_null_black():
    await NullScreenProvider().black()


async def test_null_close():
    await NullScreenProvider().close()


# ===========================================================================
# Group 2: New move types — Pydantic validation
# ===========================================================================

class TestMoveShowImage:
    def test_defaults(self):
        m = MoveShowImage(src="img.jpg")
        assert m.type == MOVE_SHOW_IMAGE
        assert m.src == "img.jpg"
        assert m.caption == ""

    def test_custom_caption(self):
        m = MoveShowImage(src="img.jpg", caption="A nice picture")
        assert m.caption == "A nice picture"

    def test_requires_src(self):
        with pytest.raises(ValidationError):
            MoveShowImage()


class TestMoveShowVideo:
    def test_basic(self):
        m = MoveShowVideo(src="video.mp4")
        assert m.type == MOVE_SHOW_VIDEO
        assert m.src == "video.mp4"

    def test_requires_src(self):
        with pytest.raises(ValidationError):
            MoveShowVideo()


class TestMoveShowIframe:
    def test_basic(self):
        m = MoveShowIframe(url="https://example.com")
        assert m.type == MOVE_SHOW_IFRAME
        assert m.url == "https://example.com"

    def test_requires_url(self):
        with pytest.raises(ValidationError):
            MoveShowIframe()


class TestMoveShowHtml:
    def test_basic(self):
        m = MoveShowHtml(html="<p>Hi</p>")
        assert m.type == MOVE_SHOW_HTML
        assert m.html == "<p>Hi</p>"

    def test_requires_html(self):
        with pytest.raises(ValidationError):
            MoveShowHtml()


class TestMoveBlackScreen:
    def test_no_args(self):
        m = MoveBlackScreen()
        assert m.type == MOVE_BLACK_SCREEN

    def test_type_string(self):
        assert MoveBlackScreen().type == "black_screen"


# ===========================================================================
# Group 3: JSON parsing via AnyMove discriminator
# ===========================================================================

_any_move_adapter: TypeAdapter[AnyMove] = TypeAdapter(AnyMove)


def test_anymove_discriminates_show_image():
    m = _any_move_adapter.validate_python({"type": "show_image", "src": "img.jpg"})
    assert isinstance(m, MoveShowImage)


def test_anymove_discriminates_show_video():
    m = _any_move_adapter.validate_python({"type": "show_video", "src": "clip.mp4"})
    assert isinstance(m, MoveShowVideo)


def test_anymove_discriminates_show_iframe():
    m = _any_move_adapter.validate_python({"type": "show_iframe", "url": "https://example.com"})
    assert isinstance(m, MoveShowIframe)


def test_anymove_discriminates_show_html():
    m = _any_move_adapter.validate_python({"type": "show_html", "html": "<b>bold</b>"})
    assert isinstance(m, MoveShowHtml)


def test_anymove_discriminates_black_screen():
    m = _any_move_adapter.validate_python({"type": "black_screen"})
    assert isinstance(m, MoveBlackScreen)


# ===========================================================================
# Group 4: New move handlers in DialogRuntime
# ===========================================================================

def _make_runtime_with_screen(make_mock_agent):
    """Return (runtime, context, screen_provider) with a screen provider wired up."""
    agent = make_mock_agent(with_screen_provider=True)
    sp = agent.orchestrator.screen_provider
    runtime = DialogRuntime(agent)
    context = RunContext()
    return runtime, context, sp


def _make_runtime_no_screen(make_mock_agent):
    """Return (runtime, context) without a screen provider."""
    agent = make_mock_agent(with_screen_provider=False)
    runtime = DialogRuntime(agent)
    context = RunContext()
    return runtime, context


async def test_handle_show_image_calls_provider(make_mock_agent):
    runtime, context, sp = _make_runtime_with_screen(make_mock_agent)
    move = MoveShowImage(src="img.jpg", caption="A photo")
    await runtime._handle_show_image(move, context)
    sp.show_image.assert_awaited_once_with("img.jpg", caption="A photo")
    entry = context.session_history[-1]
    assert entry["type"] == MOVE_SHOW_IMAGE
    assert entry["src"] == "img.jpg"
    assert entry["caption"] == "A photo"
    assert "skipped" not in entry


async def test_handle_show_image_no_provider_records_skipped(make_mock_agent):
    runtime, context = _make_runtime_no_screen(make_mock_agent)
    await runtime._handle_show_image(MoveShowImage(src="img.jpg"), context)
    entry = context.session_history[-1]
    assert entry["skipped"] is True
    assert entry["type"] == MOVE_SHOW_IMAGE


async def test_handle_show_video_calls_provider(make_mock_agent):
    runtime, context, sp = _make_runtime_with_screen(make_mock_agent)
    move = MoveShowVideo(src="clip.mp4")
    await runtime._handle_show_video(move, context)
    sp.show_video.assert_awaited_once_with("clip.mp4")
    entry = context.session_history[-1]
    assert entry["type"] == MOVE_SHOW_VIDEO
    assert entry["src"] == "clip.mp4"
    assert "skipped" not in entry


async def test_handle_show_video_no_provider_records_skipped(make_mock_agent):
    runtime, context = _make_runtime_no_screen(make_mock_agent)
    await runtime._handle_show_video(MoveShowVideo(src="clip.mp4"), context)
    assert context.session_history[-1]["skipped"] is True


async def test_handle_show_iframe_calls_provider(make_mock_agent):
    runtime, context, sp = _make_runtime_with_screen(make_mock_agent)
    move = MoveShowIframe(url="https://example.com")
    await runtime._handle_show_iframe(move, context)
    sp.show_iframe.assert_awaited_once_with("https://example.com")
    entry = context.session_history[-1]
    assert entry["type"] == MOVE_SHOW_IFRAME
    assert entry["url"] == "https://example.com"
    assert "skipped" not in entry


async def test_handle_show_iframe_no_provider_records_skipped(make_mock_agent):
    runtime, context = _make_runtime_no_screen(make_mock_agent)
    await runtime._handle_show_iframe(MoveShowIframe(url="https://example.com"), context)
    assert context.session_history[-1]["skipped"] is True


async def test_handle_show_html_calls_provider(make_mock_agent):
    runtime, context, sp = _make_runtime_with_screen(make_mock_agent)
    html = "<h1>Hello</h1>"
    move = MoveShowHtml(html=html)
    await runtime._handle_show_html(move, context)
    sp.show_html.assert_awaited_once_with(html)
    entry = context.session_history[-1]
    assert entry["type"] == MOVE_SHOW_HTML
    assert entry["html_length"] == len(html)
    assert "skipped" not in entry


async def test_handle_show_html_no_provider_records_skipped(make_mock_agent):
    runtime, context = _make_runtime_no_screen(make_mock_agent)
    await runtime._handle_show_html(MoveShowHtml(html="<p>x</p>"), context)
    assert context.session_history[-1]["skipped"] is True


async def test_handle_black_screen_calls_provider(make_mock_agent):
    runtime, context, sp = _make_runtime_with_screen(make_mock_agent)
    await runtime._handle_black_screen(MoveBlackScreen(), context)
    sp.black.assert_awaited_once()
    entry = context.session_history[-1]
    assert entry["type"] == MOVE_BLACK_SCREEN
    assert "skipped" not in entry


async def test_handle_black_screen_no_provider_records_skipped(make_mock_agent):
    runtime, context = _make_runtime_no_screen(make_mock_agent)
    await runtime._handle_black_screen(MoveBlackScreen(), context)
    assert context.session_history[-1]["skipped"] is True


# ===========================================================================
# Group 5: _handle_wait_for_web_input screen integration
# ===========================================================================

def _web_input_event(value: str) -> Event:
    return Event(
        priority=50,
        type="web_input",
        source="screen",
        data={"value": value},
        interrupt_level=InterruptLevel.BETWEEN_MOVES,
        resume_policy=ResumePolicy.DISCARD,
    )


async def test_wait_for_web_input_shows_buttons_before_wait(make_mock_agent):
    """show_buttons is called with the move options before blocking on the bus."""
    bus = EventBus()
    agent = make_mock_agent()
    sp = agent.orchestrator.screen_provider
    # Short timeout so the test finishes without a matching event.
    move = MoveWaitForWebInput(options=["Yes", "No"], timeout=0.05, default_outcome="timeout")
    runtime = DialogRuntime(agent, event_bus=bus)
    context = RunContext()

    await runtime._handle_wait_for_web_input(move, context)

    sp.show_buttons.assert_awaited_once_with(["Yes", "No"])


async def test_wait_for_web_input_hides_input_after_match(make_mock_agent):
    """hide_input is called in the finally block after a matching event is received."""
    bus = EventBus()
    agent = make_mock_agent()
    sp = agent.orchestrator.screen_provider
    move = MoveWaitForWebInput(
        options=["Yes", "No"],
        outcomes={"Yes": "confirmed"},
        default_outcome="timeout",
        timeout=2.0,
    )
    runtime = DialogRuntime(agent, event_bus=bus)
    context = RunContext()

    async def _emit():
        await asyncio.sleep(0.01)
        await bus.emit(_web_input_event("Yes"))

    asyncio.create_task(_emit())
    await runtime._handle_wait_for_web_input(move, context)

    sp.hide_input.assert_awaited_once()
    assert context.current_outcome == "confirmed"


async def test_wait_for_web_input_hides_input_after_timeout(make_mock_agent):
    """hide_input is called in the finally block when the move times out."""
    bus = EventBus()
    agent = make_mock_agent()
    sp = agent.orchestrator.screen_provider
    move = MoveWaitForWebInput(options=["Yes"], timeout=0.05, default_outcome="timed_out")
    runtime = DialogRuntime(agent, event_bus=bus)
    context = RunContext()

    await runtime._handle_wait_for_web_input(move, context)

    sp.hide_input.assert_awaited_once()
    assert context.current_outcome == "timed_out"


async def test_wait_for_web_input_no_screen_provider_resolves(make_mock_agent):
    """Correct outcome is set even without a screen provider."""
    bus = EventBus()
    agent = make_mock_agent(with_screen_provider=False)
    move = MoveWaitForWebInput(
        options=["Yes"],
        outcomes={"Yes": "ok"},
        default_outcome="timeout",
        timeout=2.0,
    )
    runtime = DialogRuntime(agent, event_bus=bus)
    context = RunContext()

    async def _emit():
        await asyncio.sleep(0.01)
        await bus.emit(_web_input_event("Yes"))

    asyncio.create_task(_emit())
    await runtime._handle_wait_for_web_input(move, context)

    assert context.current_outcome == "ok"


async def test_wait_for_web_input_no_options_does_not_show_buttons(make_mock_agent):
    """show_buttons is NOT called when the options list is empty."""
    bus = EventBus()
    agent = make_mock_agent()
    sp = agent.orchestrator.screen_provider
    move = MoveWaitForWebInput(options=[], timeout=0.05, default_outcome="timeout")
    runtime = DialogRuntime(agent, event_bus=bus)
    context = RunContext()

    await runtime._handle_wait_for_web_input(move, context)

    sp.show_buttons.assert_not_awaited()


async def test_wait_for_web_input_no_bus_hides_input(make_mock_agent):
    """Without an EventBus, the move resolves immediately and hide_input is still called."""
    agent = make_mock_agent()
    sp = agent.orchestrator.screen_provider
    move = MoveWaitForWebInput(options=["Yes"], default_outcome="timeout")
    runtime = DialogRuntime(agent, event_bus=None)
    context = RunContext()

    await runtime._handle_wait_for_web_input(move, context)

    # Buttons were shown before the early return, then input was hidden.
    sp.show_buttons.assert_awaited_once_with(["Yes"])
    sp.hide_input.assert_awaited_once()
    assert context.current_outcome == "timeout"


# ===========================================================================
# Group 6: Auto-push transcript from InteractionOrchestrator
# ===========================================================================

async def test_push_transcript_calls_show_transcript():
    """_push_transcript delegates to screen_provider.show_transcript."""
    sp = AsyncMock()
    orc = MagicMock()
    orc.screen_provider = sp

    await InteractionOrchestrator._push_transcript(orc, "Hello from robot")

    sp.show_transcript.assert_awaited_once_with("Hello from robot")


async def test_push_user_transcript_calls_show_user_transcript():
    """_push_user_transcript delegates to screen_provider.show_user_transcript."""
    sp = AsyncMock()
    orc = MagicMock()
    orc.screen_provider = sp

    await InteractionOrchestrator._push_user_transcript(orc, "Hello from user")

    sp.show_user_transcript.assert_awaited_once_with("Hello from user")


async def test_push_transcript_no_provider_does_nothing():
    """_push_transcript and _push_user_transcript are no-ops when screen_provider is None."""
    orc = MagicMock()
    orc.screen_provider = None

    # Neither call should raise.
    await InteractionOrchestrator._push_transcript(orc, "test")
    await InteractionOrchestrator._push_user_transcript(orc, "test")


# ===========================================================================
# Group 7: SICScreenAdapter — EventBus wiring and button click handling
# ===========================================================================

@pytest.fixture
def mock_sic_webserver_service():
    """Patch the SIC webserver service module in sys.modules.

    SICScreenAdapter defers all ``from sic_framework...`` imports to method
    bodies so they resolve at call time.  This fixture injects a mock module
    before each test so those lazy imports find the mock instead of requiring
    SIC to be installed.
    """
    mock_ws_service = MagicMock()
    modules_to_patch = {
        "sic_framework": MagicMock(),
        "sic_framework.services": MagicMock(),
        "sic_framework.services.webserver": MagicMock(),
        "sic_framework.services.webserver.webserver_service": mock_ws_service,
    }
    with patch.dict(sys.modules, modules_to_patch):
        yield mock_ws_service


def _make_adapter():
    """Return a (SICScreenAdapter, mock_webserver) pair."""
    ws = MagicMock()
    adapter = SICScreenAdapter(webserver=ws)
    return adapter, ws


def test_sic_constructor_registers_callback():
    adapter, ws = _make_adapter()
    ws.register_callback.assert_called_once_with(adapter._on_button_clicked)


def test_sic_button_click_before_bus_logs_warning(caplog):
    """Clicking a button before set_event_bus() logs a warning and drops the event."""
    adapter, _ = _make_adapter()
    message = MagicMock()
    message.button = {"type": "web_input", "value": "yes"}

    with caplog.at_level(logging.WARNING, logger="nardial.providers.screen.sic_adapter"):
        adapter._on_button_clicked(message)

    assert "EventBus is not set" in caplog.text


async def test_sic_button_click_after_bus_set_emits_event():
    """After set_event_bus(), button clicks are forwarded as web_input events on the bus."""
    adapter, _ = _make_adapter()
    bus = EventBus()
    bus.set_loop(asyncio.get_running_loop())
    adapter.set_event_bus(bus)

    message = MagicMock()
    message.button = {"type": "web_input", "value": "option_a"}
    adapter._on_button_clicked(message)

    # emit_sync uses call_soon_threadsafe → create_task → emit coroutine.
    # Two yields: first lets create_task run, second lets the emit coroutine complete.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert bus.has_pending(InterruptLevel.BETWEEN_MOVES)
    events = await bus.drain_at_level(InterruptLevel.BETWEEN_MOVES)
    assert len(events) == 1
    ev = events[0]
    assert ev.type == "web_input"
    assert ev.source == "screen"
    assert ev.data == {"value": "option_a"}
    assert ev.interrupt_level == InterruptLevel.BETWEEN_MOVES


async def test_sic_show_user_transcript_sends_webinfo(mock_sic_webserver_service):
    """show_user_transcript sends a role-tagged WebInfoMessage for the user."""
    adapter, ws = _make_adapter()
    await adapter.show_user_transcript("hi there")

    ws.send_message.assert_called_once()
    mock_sic_webserver_service.WebInfoMessage.assert_called_once_with(
        label="transcript", message={"role": "user", "text": "hi there"}
    )


async def test_sic_show_transcript_sends_both_messages(mock_sic_webserver_service):
    """show_transcript sends a TranscriptMessage (SIC compat) AND a role-tagged WebInfoMessage."""
    adapter, ws = _make_adapter()
    await adapter.show_transcript("hello")

    # Exactly two send_message calls: TranscriptMessage and WebInfoMessage.
    assert ws.send_message.call_count == 2
    mock_sic_webserver_service.TranscriptMessage.assert_called_once_with(transcript="hello")
    mock_sic_webserver_service.WebInfoMessage.assert_called_once_with(
        label="transcript", message={"role": "robot", "text": "hello"}
    )
