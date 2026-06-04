import sys
import os
import pytest
from types import ModuleType
from unittest.mock import Mock, AsyncMock

# Provide lightweight sic_framework stubs for unit tests.
if "sic_framework" not in sys.modules:
    sic_framework = ModuleType("sic_framework")
    core_module = ModuleType("sic_framework.core")
    sic_logging_module = ModuleType("sic_framework.core.sic_logging")
    sic_logging_module.DEBUG = 10
    sic_app_module = ModuleType("sic_framework.core.sic_application")

    class SICApplication:  # pragma: no cover - test stub
        def get_app_logger(self):
            return Mock()

        def set_log_level(self, *_args, **_kwargs):
            return None

        def set_log_file_path(self, *_args, **_kwargs):
            return None

    sic_app_module.SICApplication = SICApplication
    core_module.sic_logging = sic_logging_module
    core_module.sic_application = sic_app_module

    sys.modules["sic_framework"] = sic_framework
    sys.modules["sic_framework.core"] = core_module
    sys.modules["sic_framework.core.sic_logging"] = sic_logging_module
    sys.modules["sic_framework.core.sic_application"] = sic_app_module

from nardial.providers.nlu import NLUResult

# Ensure tests can import modules from the src/ directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))


@pytest.fixture(autouse=True)
def no_redis_connections(monkeypatch):
    """Block all Redis connections in every test.

    UserModel checks _HAS_REDIS_DS before attempting to connect; setting it to
    False keeps the model in pure in-memory mode without triggering SIC's
    SICRedisConnection (which emits a DeprecationWarning and requires a live server).
    """
    monkeypatch.setattr("nardial.user_model._HAS_REDIS_DS", False)


@pytest.fixture
def session_history():
    return []


@pytest.fixture
def user_model():
    return {}


@pytest.fixture
def topics_of_interest():
    return []


@pytest.fixture
def make_mock_agent():
    """Factory to create a simple mock ConversationAgent with configurable side-effects.

    Usage:
        agent = make_mock_agent(ask_llm_side_effect=[...], ask_open_side_effect=[...])
    The side-effect lists are wrapped so that if the mock is called more times than the
    provided sequence length, the last value is returned repeatedly instead of raising StopIteration.
    """
    def _wrap_side_effect(seq):
        if seq is None:
            return None
        seq_list = list(seq)
        if not seq_list:
            return lambda *a, **k: None
        last = seq_list[-1]

        def fn(*a, **k):
            if seq_list:
                return seq_list.pop(0)
            return last

        return fn

    def _make(ask_llm_side_effect=None, ask_open_side_effect=None,
              ask_yes_no_side_effect=None, ask_options_side_effect=None):
        agent = Mock()
        llm_effect = _wrap_side_effect(ask_llm_side_effect)
        open_effect = _wrap_side_effect(ask_open_side_effect)
        yesno_effect = _wrap_side_effect(ask_yes_no_side_effect)
        options_effect = _wrap_side_effect(ask_options_side_effect)
        agent.ask_llm = AsyncMock(side_effect=llm_effect) if ask_llm_side_effect is not None else AsyncMock(return_value=None)
        agent.ask_open = AsyncMock(side_effect=open_effect) if ask_open_side_effect is not None else AsyncMock(return_value=None)
        agent.ask_yesno = AsyncMock(side_effect=yesno_effect) if ask_yes_no_side_effect is not None else AsyncMock(return_value='no')
        agent.ask_options = AsyncMock(side_effect=options_effect) if ask_options_side_effect is not None else AsyncMock(return_value=None)
        agent.say = AsyncMock()
        agent.play_audio = Mock()
        agent.play_motion_sequence = Mock()
        agent.play_animation = Mock()
        orchestrator = Mock()
        if ask_open_side_effect is not None:
            def _listen_side_effect(*a, **k):
                transcript = open_effect(*a, **k) if open_effect is not None else None
                return NLUResult(transcript=transcript or "", intent=None)
            orchestrator.listen = AsyncMock(side_effect=_listen_side_effect)
        else:
            orchestrator.listen = AsyncMock(return_value=NLUResult(transcript="", intent=None))
        agent.orchestrator = orchestrator
        return agent

    return _make
