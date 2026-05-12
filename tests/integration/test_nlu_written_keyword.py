"""Integration tests for WrittenKeywordNLUProvider.

These tests verify the full input → NLUResult pipeline including the
``input()`` call, intent mapping, and edge-case handling. No external
services are required; ``monkeypatch`` replaces ``builtins.input``.

Run with::

    pytest tests/integration/test_nlu_written_keyword.py --integration
"""
import pytest

from nardial.providers.nlu.written_keyword import WrittenKeywordNLUProvider


@pytest.fixture
def provider():
    return WrittenKeywordNLUProvider()


# ── Yes intent ────────────────────────────────────────────────────────────────

class TestYesIntent:
    @pytest.mark.parametrize("reply", ["yes", "ja", "yep", "yeah", "yup", "correct", "right"])
    def test_canonical_yes_keywords(self, provider, monkeypatch, reply):
        monkeypatch.setattr("builtins.input", lambda _: reply)
        result = provider.listen()
        assert result.intent == "yesno_yes"
        assert result.transcript == reply

    def test_yes_keyword_in_sentence(self, provider, monkeypatch):
        # No punctuation attached: "yes" must appear as a standalone whitespace-delimited token.
        monkeypatch.setattr("builtins.input", lambda _: "I think yes")
        result = provider.listen()
        assert result.intent == "yesno_yes"

    def test_yes_is_case_insensitive(self, provider, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "YES please")
        result = provider.listen()
        assert result.intent == "yesno_yes"


# ── No intent ─────────────────────────────────────────────────────────────────

class TestNoIntent:
    @pytest.mark.parametrize("reply", ["no", "nee", "nope", "nah", "wrong"])
    def test_canonical_no_keywords(self, provider, monkeypatch, reply):
        monkeypatch.setattr("builtins.input", lambda _: reply)
        result = provider.listen()
        assert result.intent == "yesno_no"

    def test_no_keyword_in_sentence(self, provider, monkeypatch):
        # No punctuation attached: "no" must appear as a standalone whitespace-delimited token.
        monkeypatch.setattr("builtins.input", lambda _: "I say no")
        result = provider.listen()
        assert result.intent == "yesno_no"


# ── Don't-know intent ─────────────────────────────────────────────────────────

class TestDontKnowIntent:
    @pytest.mark.parametrize("reply", ["don't know", "dont know", "not sure", "maybe", "idk", "dunno"])
    def test_canonical_dontknow_phrases(self, provider, monkeypatch, reply):
        monkeypatch.setattr("builtins.input", lambda _: reply)
        result = provider.listen()
        assert result.intent == "yesno_dontknow"

    def test_dontknow_takes_precedence_over_yes_keyword(self, provider, monkeypatch):
        """'maybe yes' contains both 'maybe' and 'yes'; dontknow wins because it is checked first."""
        monkeypatch.setattr("builtins.input", lambda _: "maybe yes")
        result = provider.listen()
        assert result.intent == "yesno_dontknow"


# ── Free-text (no intent) ──────────────────────────────────────────────────────

class TestFreeTextNoIntent:
    def test_unrecognised_word_returns_none_intent(self, provider, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "I love pizza")
        result = provider.listen()
        assert result.intent is None
        assert result.transcript == "I love pizza"

    def test_number_returns_none_intent(self, provider, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "42")
        result = provider.listen()
        assert result.intent is None


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_input_returns_empty_result(self, provider, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "")
        result = provider.listen()
        assert result.transcript == ""
        assert result.intent is None

    def test_whitespace_only_returns_empty_result(self, provider, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "   ")
        result = provider.listen()
        assert result.transcript == ""
        assert result.intent is None

    def test_eof_error_returns_empty_result(self, provider, monkeypatch):
        def raise_eof(_):
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        result = provider.listen()
        assert result.transcript == ""
        assert result.intent is None

    def test_context_parameter_accepted(self, provider, monkeypatch):
        """The context kwarg must be forwarded to input() without error."""
        monkeypatch.setattr("builtins.input", lambda _: "yes")
        result = provider.listen(context="Do you agree?")
        assert result.intent == "yesno_yes"

    def test_result_is_nlu_result_instance(self, provider, monkeypatch):
        from nardial.providers.nlu import NLUResult

        monkeypatch.setattr("builtins.input", lambda _: "yes")
        result = provider.listen()
        assert isinstance(result, NLUResult)
