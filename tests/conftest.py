import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock

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
    """Factory to create an async mock ConversationAgent for use with DialogRuntime.

    All I/O methods (``say``, ``ask_yesno``, ``ask_open``, ``ask_options``,
    ``ask_llm``) are ``AsyncMock`` instances; ``play_audio``,
    ``play_motion_sequence``, and ``play_animation`` are regular ``MagicMock``
    instances (they are not awaited by the runtime).

    Usage:
        agent = make_mock_agent(ask_llm_side_effect=[...], ask_open_side_effect=[...])

    Side-effect lists are wrapped so that if the mock is called more times than
    the provided sequence length, the last value is returned repeatedly instead
    of raising ``StopIteration``.
    """
    def _wrap_async_side_effect(seq):
        if seq is None:
            return None
        seq_list = list(seq)
        if not seq_list:
            async def _empty(*a, **k):
                return None
            return _empty
        last = seq_list[-1]

        async def _fn(*a, **k):
            if seq_list:
                return seq_list.pop(0)
            return last

        return _fn

    def _make(ask_llm_side_effect=None, ask_open_side_effect=None,
              ask_yes_no_side_effect=None, ask_options_side_effect=None):
        agent = MagicMock()

        open_effect = _wrap_async_side_effect(ask_open_side_effect)

        agent.ask_llm = (
            AsyncMock(side_effect=_wrap_async_side_effect(ask_llm_side_effect))
            if ask_llm_side_effect is not None
            else AsyncMock(return_value=None)
        )
        agent.ask_open = (
            AsyncMock(side_effect=open_effect)
            if ask_open_side_effect is not None
            else AsyncMock(return_value=None)
        )
        agent.ask_yesno = (
            AsyncMock(side_effect=_wrap_async_side_effect(ask_yes_no_side_effect))
            if ask_yes_no_side_effect is not None
            else AsyncMock(return_value="no")
        )
        agent.ask_options = (
            AsyncMock(side_effect=_wrap_async_side_effect(ask_options_side_effect))
            if ask_options_side_effect is not None
            else AsyncMock(return_value=None)
        )
        agent.say = AsyncMock()
        agent.play_audio = MagicMock()
        agent.play_motion_sequence = MagicMock()
        agent.play_animation = MagicMock()
        agent.personalize = MagicMock(return_value=None)

        orchestrator = MagicMock()
        if ask_open_side_effect is not None:
            captured = open_effect

            async def _listen(*a, **k):
                transcript = await captured(*a, **k) if captured is not None else None
                return NLUResult(transcript=transcript or "", intent=None)

            orchestrator.listen = AsyncMock(side_effect=_listen)
        else:
            orchestrator.listen = AsyncMock(return_value=NLUResult(transcript="", intent=None))

        agent.orchestrator = orchestrator
        return agent

    return _make
