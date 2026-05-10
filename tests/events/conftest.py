"""Async test infrastructure for the events package.

``make_async_mock_agent`` mirrors the sync ``make_mock_agent`` factory in
``tests/conftest.py`` but returns ``AsyncMock`` instances for every agent
method that will become ``async`` after Phase 4.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from nardial.providers.nlu import NLUResult


def _wrap_async_side_effect(seq):
    """Return an async callable that pops from ``seq``, repeating the last value when exhausted."""
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


def make_async_mock_agent(
    ask_llm_side_effect=None,
    ask_open_side_effect=None,
    ask_yes_no_side_effect=None,
    ask_options_side_effect=None,
):
    """Build an async mock ConversationAgent suitable for async dialog tests.

    Parameters mirror the sync ``make_mock_agent`` factory so tests can switch
    between sync and async agents with minimal changes.
    """
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
    agent.play_audio = AsyncMock()
    agent.play_motion_sequence = AsyncMock()
    agent.play_animation = AsyncMock()

    orchestrator = MagicMock()
    if ask_open_side_effect is not None:
        captured_open_effect = open_effect

        async def _listen(*a, **k):
            transcript = await captured_open_effect(*a, **k) if captured_open_effect is not None else None
            return NLUResult(transcript=transcript or "", intent=None)

        orchestrator.listen = AsyncMock(side_effect=_listen)
    else:
        orchestrator.listen = AsyncMock(return_value=NLUResult(transcript="", intent=None))

    agent.orchestrator = orchestrator
    return agent


@pytest.fixture
def async_mock_agent():
    """Fixture that returns the ``make_async_mock_agent`` factory.

    Usage in tests::

        async def test_something(async_mock_agent):
            agent = async_mock_agent(ask_llm_side_effect=["Hello!"])
            ...
    """
    return make_async_mock_agent
