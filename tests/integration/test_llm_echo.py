"""Integration tests for EchoLLMProvider.

These tests verify the complete ``complete()`` call path including message
ordering, role filtering, and edge-case inputs. No external services or API
keys are required; EchoLLMProvider is entirely in-process.

Run with::

    pytest tests/integration/test_llm_echo.py --integration
"""
import pytest

from nardial.providers.llm import Message
from nardial.providers.llm.echo import EchoLLMProvider


@pytest.fixture
def provider():
    return EchoLLMProvider()


# ── Basic last-user-message behaviour ─────────────────────────────────────────

class TestLastUserMessage:
    def test_returns_last_user_message(self, provider):
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
            Message(role="user", content="How are you?"),
        ]
        assert provider.complete(messages) == "How are you?"

    def test_single_user_message(self, provider):
        messages = [Message(role="user", content="ping")]
        assert provider.complete(messages) == "ping"

    def test_ignores_assistant_messages(self, provider):
        messages = [
            Message(role="assistant", content="I said this"),
            Message(role="user", content="user said this"),
        ]
        assert provider.complete(messages) == "user said this"

    def test_ignores_system_messages(self, provider):
        messages = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="actual question"),
        ]
        assert provider.complete(messages) == "actual question"


# ── Multi-turn conversations ───────────────────────────────────────────────────

class TestMultiTurn:
    def test_picks_last_not_first_user_turn(self, provider):
        messages = [
            Message(role="user", content="first question"),
            Message(role="assistant", content="answer one"),
            Message(role="user", content="follow-up question"),
            Message(role="assistant", content="answer two"),
            Message(role="user", content="final question"),
        ]
        assert provider.complete(messages) == "final question"

    def test_system_prompt_parameter_accepted_but_not_echoed(self, provider):
        messages = [Message(role="user", content="hello")]
        result = provider.complete(messages, system_prompt="Be concise.")
        assert result == "hello"

    def test_long_history_returns_last_user_turn(self, provider):
        messages = [
            Message(role="user", content=f"turn {i}") if i % 2 == 0
            else Message(role="assistant", content=f"reply {i}")
            for i in range(10)
        ]
        # Last even index: 8  → "turn 8"
        last_user = next(
            m.content for m in reversed(messages) if m.role == "user"
        )
        assert provider.complete(messages) == last_user


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_message_list_returns_empty_string(self, provider):
        assert provider.complete([]) == ""

    def test_system_only_messages_returns_empty_string(self, provider):
        messages = [Message(role="system", content="You are helpful.")]
        assert provider.complete(messages) == ""

    def test_assistant_only_messages_returns_empty_string(self, provider):
        messages = [Message(role="assistant", content="I was first.")]
        assert provider.complete(messages) == ""

    def test_empty_user_content_is_returned_verbatim(self, provider):
        messages = [Message(role="user", content="")]
        assert provider.complete(messages) == ""

    def test_multiline_user_content_preserved(self, provider):
        text = "line one\nline two\nline three"
        messages = [Message(role="user", content=text)]
        assert provider.complete(messages) == text

    def test_unicode_content_preserved(self, provider):
        text = "Héllo wörld 🌍"
        messages = [Message(role="user", content=text)]
        assert provider.complete(messages) == text

    def test_result_is_str(self, provider):
        messages = [Message(role="user", content="test")]
        assert isinstance(provider.complete(messages), str)

    def test_provider_is_llm_provider_instance(self, provider):
        from nardial.providers.llm import LLMProvider

        assert isinstance(provider, LLMProvider)
