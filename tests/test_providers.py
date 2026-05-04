"""Tests for provider protocols and their null/echo implementations."""
import pytest

from nardial.providers.tts import TTSProvider
from nardial.providers.tts.null import NullTTSProvider
from nardial.providers.nlu import NLUProvider, NLUResult
from nardial.providers.nlu.written_keyword import WrittenKeywordNLUProvider
from nardial.providers.llm import LLMProvider, Message
from nardial.providers.llm.echo import EchoLLMProvider
from nardial.providers.vector_store import VectorStoreProvider
from nardial.providers.vector_store.null import NullVectorStoreProvider
from nardial.interaction_orchestrator import InteractionConfig


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

def test_null_tts_satisfies_protocol():
    assert isinstance(NullTTSProvider(), TTSProvider)


def test_null_vector_store_satisfies_protocol():
    assert isinstance(NullVectorStoreProvider(), VectorStoreProvider)


def test_echo_llm_satisfies_protocol():
    assert isinstance(EchoLLMProvider(), LLMProvider)


# WrittenKeywordNLUProvider uses stdin so we test protocol conformance via duck-typing
def test_written_keyword_nlu_satisfies_protocol():
    assert isinstance(WrittenKeywordNLUProvider(), NLUProvider)


# ---------------------------------------------------------------------------
# NullTTSProvider
# ---------------------------------------------------------------------------

def test_null_tts_speak_is_noop():
    tts = NullTTSProvider()
    tts.speak("hello")  # should not raise


def test_null_tts_close_is_noop():
    tts = NullTTSProvider()
    tts.close()  # should not raise


# ---------------------------------------------------------------------------
# NullVectorStoreProvider
# ---------------------------------------------------------------------------

def test_null_vector_store_query_returns_empty():
    store = NullVectorStoreProvider()
    assert store.query("anything") == []


def test_null_vector_store_query_ignores_index_name():
    store = NullVectorStoreProvider()
    assert store.query("q", index_name="my_index", k=10) == []


def test_null_vector_store_ingest_is_noop():
    store = NullVectorStoreProvider()
    store.ingest()  # should not raise


def test_null_vector_store_close_is_noop():
    store = NullVectorStoreProvider()
    store.close()  # should not raise


# ---------------------------------------------------------------------------
# EchoLLMProvider
# ---------------------------------------------------------------------------

def test_echo_llm_returns_last_user_message():
    llm = EchoLLMProvider()
    messages = [Message(role="user", content="hello world")]
    assert llm.complete(messages) == "hello world"


def test_echo_llm_returns_last_user_message_from_conversation():
    llm = EchoLLMProvider()
    messages = [
        Message(role="user", content="first"),
        Message(role="assistant", content="reply"),
        Message(role="user", content="second"),
    ]
    assert llm.complete(messages) == "second"


def test_echo_llm_empty_messages_returns_empty():
    llm = EchoLLMProvider()
    assert llm.complete([]) == ""


def test_echo_llm_ignores_system_prompt():
    llm = EchoLLMProvider()
    messages = [Message(role="user", content="test")]
    assert llm.complete(messages, system_prompt="irrelevant") == "test"


# ---------------------------------------------------------------------------
# WrittenKeywordNLUProvider intent matching (no stdin required)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected_intent", [
    ("yes", "yesno_yes"),
    ("yeah sure", "yesno_yes"),
    ("yep", "yesno_yes"),
    ("no", "yesno_no"),
    ("nope", "yesno_no"),
    ("i don't know", "yesno_dontknow"),
    ("not sure", "yesno_dontknow"),
    ("idk", "yesno_dontknow"),
    ("I love pizza", None),
    ("", None),
])
def test_written_keyword_intent_mapping(text, expected_intent):
    nlu = WrittenKeywordNLUProvider()
    assert nlu._match_intent(text.lower()) == expected_intent


# ---------------------------------------------------------------------------
# NLUResult dataclass
# ---------------------------------------------------------------------------

def test_nlu_result_defaults():
    result = NLUResult(transcript="hello")
    assert result.transcript == "hello"
    assert result.intent is None
    assert result.confidence == 0.0


def test_nlu_result_with_intent():
    result = NLUResult(transcript="yes", intent="yesno_yes", confidence=0.95)
    assert result.intent == "yesno_yes"
    assert result.confidence == 0.95


# ---------------------------------------------------------------------------
# InteractionConfig
# ---------------------------------------------------------------------------

def test_interaction_config_defaults():
    config = InteractionConfig()
    assert config.language == "en"
    assert config.post_speech_delay is None
    assert config.signal_listening_behavior is True
    assert config.animated is True
    assert config.chunk_audio is True


def test_interaction_config_custom_values():
    config = InteractionConfig(language="nl", post_speech_delay=1.5, signal_listening_behavior=False)
    assert config.language == "nl"
    assert config.post_speech_delay == 1.5
    assert config.signal_listening_behavior is False
