"""Tests for VAD endpointing: stop listening after the user has spoken and then been silent."""
import importlib
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from nardial.authoring.factory import MoveFactory
from nardial.interaction_orchestrator import InteractionConfig, InteractionOrchestrator
from nardial.listen_settings import ListenSettings, validate_listen_settings
from nardial.mini_dialogs import MiniDialog
from nardial.moves import MoveAskLLM
from nardial.providers.nlu import NLUResult
from nardial.providers.vad import VADProvider


class FakeVAD:
    """Plays (seconds before it, is_speaking) events from a thread once started."""

    def __init__(self, events):
        self.events = list(events)
        self.on_change = None
        self.started = 0
        self.closed = False

    def start(self, on_change):
        self.started += 1
        self.on_change = on_change
        events = self.events

        def play():
            for delay, is_speaking in events:
                time.sleep(delay)
                on_change(is_speaking)

        threading.Thread(target=play, daemon=True).start()

    def stop(self):
        self.on_change = None

    def close(self):
        self.closed = True


class BlockingNLU:
    """Listens until cancelled or timed out; remembers when it was cancelled."""

    def __init__(self):
        self.stopped = threading.Event()
        self.cancelled_at = None

    def listen(self, context=None, timeout=10.0):
        self.stopped.clear()
        self.stopped.wait(timeout)
        return NLUResult(transcript="heard so far")

    def cancel(self):
        self.cancelled_at = time.monotonic()
        self.stopped.set()


def _make_orchestrator(vad, **config):
    # Skip __init__, which sets up logging and SIC services.
    orch = object.__new__(InteractionOrchestrator)
    orch.interaction_conf = InteractionConfig(signal_listening_behavior=False, **config)
    orch.nlu_provider = BlockingNLU()
    orch.vad_provider = vad
    orch.logger = Mock()
    orch._log_queue = None
    orch.screen_provider = None
    orch.control = None
    return orch


# ---------------------------------------------------------------------------
# Settings and moves
# ---------------------------------------------------------------------------

def test_vad_endpointing_off_by_default():
    settings = InteractionConfig().resolve_listen_settings("ask_open")
    assert settings.vad_endpointing is False
    assert settings.vad_silence_delay == ListenSettings().vad_silence_delay


def test_vad_settings_precedence():
    config = InteractionConfig(vad_endpointing=True, vad_silence_delay=0.4,
                               listen_settings={"ask_open": {"vad_silence_delay": 1.0}})
    assert config.resolve_listen_settings("ask_yesno").vad_silence_delay == 0.4
    assert config.resolve_listen_settings("ask_open").vad_silence_delay == 1.0
    move = config.resolve_listen_settings("ask_open", {"vad_endpointing": False})
    assert move.vad_endpointing is False and move.vad_silence_delay == 1.0


def test_validate_vad_settings():
    assert validate_listen_settings({"vad_endpointing": True, "vad_silence_delay": 1}, "m") == []
    assert validate_listen_settings({"vad_endpointing": "yes"}, "m") == ["m.vad_endpointing must be bool"]
    assert validate_listen_settings({"vad_silence_delay": -1}, "m") == ["m.vad_silence_delay must not be negative"]


def test_ask_llm_move_listen_settings():
    assert MoveFactory.validate({"type": "ask_llm", "prompt": "p", "vad_endpointing": True}) == []
    assert MoveFactory.validate({"type": "ask_llm", "prompt": "p", "vad_silence_delay": "1"}) == [
        "moves[0].vad_silence_delay must be int or float"]
    move = MoveAskLLM.from_dict({"prompt": "p", "vad_endpointing": True, "vad_silence_delay": 1.2})
    assert move.listen_settings == {"vad_endpointing": True, "vad_silence_delay": 1.2}


async def test_ask_llm_passes_listen_type_and_settings(make_mock_agent):
    agent = make_mock_agent(ask_llm_side_effect=["hello", "bye"])
    md = MiniDialog('test', moves=[])
    md.set_conversation_config(agent, [], [], {})

    await md.handle_move_ask_llm({"type": "ask_llm", "prompt": "p", "max_turns": 1, "vad_endpointing": True})
    kwargs = agent.orchestrator.listen.call_args.kwargs
    assert kwargs["listen_type"] == "ask_llm"
    assert kwargs["listen_settings"] == {"vad_endpointing": True}


# ---------------------------------------------------------------------------
# InteractionOrchestrator
# ---------------------------------------------------------------------------

async def test_stops_listening_after_silence_following_speech():
    vad = FakeVAD([(0.05, True), (0.2, False)])
    orch = _make_orchestrator(vad, vad_endpointing=True, vad_silence_delay=0.2)

    start = time.monotonic()
    result = await orch.listen(timeout=5)
    assert result.transcript == "heard so far"
    # speech ends at ~0.25 s, listening stops 0.2 s later
    assert 0.4 <= orch.nlu_provider.cancelled_at - start < 1.0
    assert vad.on_change is None  # stopped after the listen


async def test_silence_before_speech_does_not_stop_listening():
    # Silence reported before the user said anything (e.g. the end of the robot's own speech).
    vad = FakeVAD([(0.0, False)])
    orch = _make_orchestrator(vad, vad_endpointing=True, vad_silence_delay=0.05)

    await orch.listen(timeout=0.4)
    assert orch.nlu_provider.cancelled_at is None  # ended by the timeout


async def test_speech_resuming_restarts_silence_wait():
    # A pause shorter than vad_silence_delay does not stop listening.
    vad = FakeVAD([(0.0, True), (0.1, False), (0.1, True), (0.2, False)])
    orch = _make_orchestrator(vad, vad_endpointing=True, vad_silence_delay=0.25)

    start = time.monotonic()
    await orch.listen(timeout=5)
    # last speech ends at ~0.4 s, listening stops 0.25 s later (not at 0.1 + 0.25 s)
    assert orch.nlu_provider.cancelled_at - start >= 0.6


@pytest.mark.parametrize("config,listen_settings", [
    ({}, None),  # off by default
    ({"vad_endpointing": True}, {"vad_endpointing": False}),  # turned off for the move
])
async def test_vad_not_used_when_off(config, listen_settings):
    vad = FakeVAD([(0.0, True), (0.0, False)])
    orch = _make_orchestrator(vad, **config)

    await orch.listen(timeout=0.2, listen_settings=listen_settings)
    assert vad.started == 0
    assert orch.nlu_provider.cancelled_at is None


async def test_vad_endpointing_without_vad_provider_listens_normally():
    orch = _make_orchestrator(None, vad_endpointing=True)
    assert (await orch.listen(timeout=0.1)).transcript == "heard so far"


def test_fake_vad_satisfies_protocol():
    assert isinstance(FakeVAD([]), VADProvider)


# ---------------------------------------------------------------------------
# SICVoiceDetectionProvider
# ---------------------------------------------------------------------------

@pytest.fixture
def sic_vad_provider(monkeypatch):
    """Import SICVoiceDetectionProvider against a stubbed SIC voice detection service."""
    connector = Mock()
    module = ModuleType("sic_framework.services.voice_detection.voice_detection")
    module.VoiceDetection = Mock(return_value=connector)
    module.VoiceDetectionConf = type("VoiceDetectionConf", (), {})
    monkeypatch.setitem(sys.modules, "sic_framework.services", ModuleType("sic_framework.services"))
    monkeypatch.setitem(sys.modules, "sic_framework.services.voice_detection",
                        ModuleType("sic_framework.services.voice_detection"))
    monkeypatch.setitem(sys.modules, "sic_framework.services.voice_detection.voice_detection", module)
    monkeypatch.delitem(sys.modules, "nardial.providers.vad.sic_voice_detection", raising=False)

    provider_module = importlib.import_module("nardial.providers.vad.sic_voice_detection")
    mic = object()
    provider = provider_module.SICVoiceDetectionProvider(mic=mic)
    assert module.VoiceDetection.call_args.kwargs["input_source"] is mic
    return provider, connector


def test_sic_vad_forwards_speech_changes_only_while_started(sic_vad_provider):
    provider, connector = sic_vad_provider
    on_message = connector.register_callback.call_args.args[0]
    changes = []

    on_message(SimpleNamespace(is_speaking=True))  # not started yet
    provider.start(changes.append)
    on_message(SimpleNamespace(is_speaking=True, speech_proportion=0.8))
    on_message(SimpleNamespace(is_speaking=False, speech_proportion=0.0))
    on_message(SimpleNamespace())  # not a voice detection message
    provider.stop()
    on_message(SimpleNamespace(is_speaking=True))

    assert changes == [True, False]
    assert isinstance(provider, VADProvider)
