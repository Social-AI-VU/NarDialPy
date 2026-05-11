"""Tests for ConversationAgent.ask_yesno and ask_open.

ConversationAgent wraps InteractionOrchestrator, which has heavyweight __init__
side-effects (SIC framework, device setup). Tests here patch
InteractionOrchestrator at the module level so ConversationAgent can be
instantiated with a plain AsyncMock orchestrator and no real services.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from nardial.conversation_agent import ConversationAgent
from nardial.providers.nlu import (
    NLUResult,
    INTENT_YESNO_YES,
    INTENT_YESNO_NO,
    INTENT_YESNO_DONTKNOW,
)


@pytest.fixture
def agent(monkeypatch):
    """A real ConversationAgent whose orchestrator is an AsyncMock.

    InteractionOrchestrator is replaced by a factory that returns a fresh
    AsyncMock so every test gets an isolated orchestrator with no live services.
    """
    mock_orch = MagicMock()
    mock_orch.say = AsyncMock()
    mock_orch.listen = AsyncMock(return_value=NLUResult(transcript="", intent=None))
    mock_orch.request_from_llm = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "nardial.conversation_agent.InteractionOrchestrator",
        MagicMock(return_value=mock_orch),
    )
    return ConversationAgent(device=MagicMock(), tts_provider=MagicMock(), nlu_provider=MagicMock())


# ---------------------------------------------------------------------------
# ask_yesno
# ---------------------------------------------------------------------------

class TestAskYesNo:
    """ask_yesno maps NLU intents to canonical string responses."""

    async def test_yes_intent_returns_yes(self, agent):
        agent.orchestrator.listen.return_value = NLUResult(
            transcript="yes", intent=INTENT_YESNO_YES
        )
        assert await agent.ask_yesno("Do you like this?") == "yes"

    async def test_no_intent_returns_no(self, agent):
        agent.orchestrator.listen.return_value = NLUResult(
            transcript="no", intent=INTENT_YESNO_NO
        )
        assert await agent.ask_yesno("Do you like this?") == "no"

    async def test_dontknow_intent_returns_dontknow(self, agent):
        agent.orchestrator.listen.return_value = NLUResult(
            transcript="not sure", intent=INTENT_YESNO_DONTKNOW
        )
        assert await agent.ask_yesno("Do you know?") == "dontknow"

    async def test_unrecognised_intent_returns_none(self, agent):
        agent.orchestrator.listen.return_value = NLUResult(
            transcript="hello", intent="some_other_intent"
        )
        assert await agent.ask_yesno("Do you like this?") is None

    async def test_no_intent_at_all_returns_none(self, agent):
        agent.orchestrator.listen.return_value = NLUResult(transcript="", intent=None)
        assert await agent.ask_yesno("Do you like this?") is None

    async def test_question_is_spoken_before_listening(self, agent):
        agent.orchestrator.listen.return_value = NLUResult(
            transcript="yes", intent=INTENT_YESNO_YES
        )
        await agent.ask_yesno("Are you ready?")
        agent.orchestrator.say.assert_called_once_with("Are you ready?")


# ---------------------------------------------------------------------------
# ask_open
# ---------------------------------------------------------------------------

class TestAskOpen:
    """ask_open returns the user transcript or None when nothing is captured."""

    async def test_returns_transcript_on_first_attempt(self, agent):
        agent.orchestrator.listen.return_value = NLUResult(transcript="I like cats")
        assert await agent.ask_open("What do you like?") == "I like cats"

    async def test_returns_none_after_all_attempts_empty(self, agent):
        agent.orchestrator.listen.return_value = NLUResult(transcript="")
        assert await agent.ask_open("What do you like?", max_attempts=2) is None

    async def test_retries_on_empty_then_succeeds(self, agent):
        agent.orchestrator.listen.side_effect = [
            NLUResult(transcript=""),
            NLUResult(transcript="I like dogs"),
        ]
        assert await agent.ask_open("What do you like?", max_attempts=2) == "I like dogs"

    async def test_question_is_spoken_each_attempt(self, agent):
        agent.orchestrator.listen.return_value = NLUResult(transcript="")
        await agent.ask_open("What do you like?", max_attempts=2)
        assert agent.orchestrator.say.call_count == 2
