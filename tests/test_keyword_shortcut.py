"""Tests for the keyword shortcut: keyword matching, listen settings and early stopping."""
import threading
import time
from unittest.mock import AsyncMock, Mock

import pytest

from nardial.authoring.factory import MoveFactory
from nardial.conversation_agent import ConversationAgent
from nardial.interaction_orchestrator import InteractionConfig, InteractionOrchestrator
from nardial.listen_settings import ListenSettings, validate_listen_settings
from nardial.mini_dialogs import MiniDialog
from nardial.moves import MoveAskOpen, MoveAskOptions, MoveAskYesNo
from nardial.providers.nlu import NLUResult, INTENT_YESNO_YES, INTENT_YESNO_NO, INTENT_YESNO_DONTKNOW
from nardial.providers.nlu.keywords import YESNO_KEYWORDS, match_keywords, yesno_keywords

NL = YESNO_KEYWORDS["nl"]
EN = YESNO_KEYWORDS["en"]


# ---------------------------------------------------------------------------
# match_keywords
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("ja", INTENT_YESNO_YES),
    ("Ja!", INTENT_YESNO_YES),
    ("oké", INTENT_YESNO_YES),
    ("oke", INTENT_YESNO_YES),
    ("ja hoor", INTENT_YESNO_YES),
    ("zeker", INTENT_YESNO_YES),
    ("nee", INTENT_YESNO_NO),
    ("zeker niet", INTENT_YESNO_NO),
    ("helemaal niet", INTENT_YESNO_NO),
    ("weet ik niet", INTENT_YESNO_DONTKNOW),
    ("geen idee", INTENT_YESNO_DONTKNOW),
    ("misschien", INTENT_YESNO_DONTKNOW),
    ("niet goed", None),  # yes and no both match: let the NLU provider decide
    ("een draak", None),
    ("", None),
])
def test_match_dutch(text, expected):
    assert match_keywords(text, NL, max_words=3) == expected


@pytest.mark.parametrize("text,expected", [
    ("yes", INTENT_YESNO_YES),
    ("Yeah.", INTENT_YESNO_YES),
    ("of course", INTENT_YESNO_YES),
    ("of course not", INTENT_YESNO_NO),
    ("no", INTENT_YESNO_NO),
    ("not really", INTENT_YESNO_NO),
    ("I don't know", INTENT_YESNO_DONTKNOW),
    ("I don’t know", INTENT_YESNO_DONTKNOW),  # typographic apostrophe
    ("no idea", INTENT_YESNO_DONTKNOW),
    ("yeah no", None),
    ("now", None),  # whole words only
    ("know", None),
    ("yesterday", None),
])
def test_match_english(text, expected):
    assert match_keywords(text, EN, max_words=3) == expected


def test_match_rejects_long_answers():
    assert match_keywords("yes but I would rather not", EN, max_words=3) is None
    assert match_keywords("yes but I would rather not", {"yes": ["yes"]}) == "yes"


def test_match_options_as_labels():
    options = {"ice cream": ["ice cream"], "cake": ["cake"]}
    assert match_keywords("Ice cream", options, max_words=3) == "ice cream"
    assert match_keywords("cake please", options, max_words=3) == "cake"
    assert match_keywords("cake or ice cream", options, max_words=5) is None


@pytest.mark.parametrize("language,expected", [("nl", NL), ("nl-NL", NL), ("en_US", EN), ("EN", EN), ("fr", {}),
                                               (None, {})])
def test_yesno_keywords_language(language, expected):
    assert yesno_keywords(language) == expected


def test_yesno_keywords_override_replaces_one_intent():
    keywords = yesno_keywords("nl", {INTENT_YESNO_NO: NL[INTENT_YESNO_NO] + ["heb ik niet"]})
    assert match_keywords("heb ik niet", keywords) == INTENT_YESNO_NO
    assert keywords[INTENT_YESNO_YES] == NL[INTENT_YESNO_YES]
    assert "heb ik niet" not in NL[INTENT_YESNO_NO]  # defaults are not changed


# ---------------------------------------------------------------------------
# Listen settings: move > recognition type > agent > default
# ---------------------------------------------------------------------------

def test_listen_settings_defaults():
    assert InteractionConfig().resolve_listen_settings("ask_yesno") == ListenSettings()
    assert ListenSettings().keyword_shortcut is True


def test_listen_settings_precedence():
    config = InteractionConfig(keyword_shortcut=False, listen_settings={
        "ask_yesno": {"keyword_shortcut": True, "keyword_max_words": 2},
    })
    assert config.resolve_listen_settings("ask_options").keyword_shortcut is False
    assert config.resolve_listen_settings("ask_yesno") == ListenSettings(keyword_shortcut=True, keyword_max_words=2)
    move = config.resolve_listen_settings("ask_yesno", {"keyword_shortcut": False})
    assert move == ListenSettings(keyword_shortcut=False, keyword_max_words=2)


def test_validate_listen_settings():
    assert validate_listen_settings({"keyword_shortcut": False, "keyword_confirm_delay": 0}, "m") == []
    assert validate_listen_settings({"keyword_shortcut": "no"}, "m") == ["m.keyword_shortcut must be bool"]
    assert validate_listen_settings({"keyword_max_words": True}, "m") == ["m.keyword_max_words must be int"]
    assert validate_listen_settings({"keyword_max_words": 0}, "m") == ["m.keyword_max_words must be at least 1"]


def test_move_factory_validates_listen_settings():
    assert MoveFactory.validate({"type": "ask_yesno", "text": "Q?", "keyword_shortcut": False}) == []
    errs = MoveFactory.validate({"type": "ask_options", "text": "Q?", "options": ["a"], "keyword_shortcut": 1})
    assert errs == ["moves[0].keyword_shortcut must be bool"]


@pytest.mark.parametrize("move_class,extra", [(MoveAskYesNo, {}), (MoveAskOpen, {}), (MoveAskOptions, {"options": ["a"]})])
def test_moves_read_listen_settings(move_class, extra):
    move = move_class.from_dict({"text": "Q?", "keyword_shortcut": False, "set_variable": "x", **extra})
    assert move.listen_settings == {"keyword_shortcut": False}
    assert move_class.from_dict({"text": "Q?", **extra}).listen_settings == {}


@pytest.mark.parametrize("move_type,handler,agent_method,extra", [
    ("ask_open", "handle_move_ask_open", "ask_open", {}),
    ("ask_yesno", "handle_move_ask_yesno", "ask_yesno", {}),
    ("ask_options", "handle_move_ask_options", "ask_options", {"options": ["a", "b"]}),
])
async def test_move_listen_settings_are_passed(make_mock_agent, move_type, handler, agent_method, extra):
    agent = make_mock_agent()
    md = MiniDialog('test', moves=[])
    md.set_conversation_config(agent, [], [], {})

    await getattr(md, handler)({"type": move_type, "text": "Q?", "keyword_shortcut": False, **extra})
    assert getattr(agent, agent_method).call_args.kwargs["listen_settings"] == {"keyword_shortcut": False}

    await getattr(md, handler)({"type": move_type, "text": "Q?", **extra})
    assert "listen_settings" not in getattr(agent, agent_method).call_args.kwargs


# ---------------------------------------------------------------------------
# ConversationAgent passes the expected answers
# ---------------------------------------------------------------------------

@pytest.fixture
def agent(monkeypatch):
    mock_orch = Mock()
    mock_orch.say = AsyncMock()
    mock_orch.listen = AsyncMock()
    mock_orch.interaction_conf = InteractionConfig(language="nl")
    monkeypatch.setattr("nardial.conversation_agent.InteractionOrchestrator", Mock(return_value=mock_orch))
    return ConversationAgent(device=Mock(), tts_provider=Mock(), nlu_provider=Mock())


async def test_ask_yesno_passes_yesno_keywords(agent):
    agent.orchestrator.listen.return_value = NLUResult(transcript="ja", intent=INTENT_YESNO_YES)
    assert await agent.ask_yesno("Q?", listen_settings={"keyword_shortcut": False}) == "yes"
    kwargs = agent.orchestrator.listen.call_args.kwargs
    assert kwargs["listen_type"] == "ask_yesno"
    assert kwargs["keywords"] == NL
    assert kwargs["listen_settings"] == {"keyword_shortcut": False}


async def test_ask_options_returns_option_matched_by_shortcut(agent):
    agent.orchestrator.listen.return_value = NLUResult(transcript="Ijs", intent="ijs")
    assert await agent.ask_options("Q?", ["taart", "ijs"]) == "ijs"
    kwargs = agent.orchestrator.listen.call_args.kwargs
    assert kwargs["listen_type"] == "ask_options"
    assert kwargs["keywords"] == {"taart": ["taart"], "ijs": ["ijs"]}


async def test_ask_options_still_matches_transcript_without_shortcut(agent):
    agent.orchestrator.listen.return_value = NLUResult(transcript="doe maar taart", intent=None)
    assert await agent.ask_options("Q?", ["taart", "ijs"]) == "taart"


# ---------------------------------------------------------------------------
# InteractionOrchestrator early stop
# ---------------------------------------------------------------------------

class StreamingProvider:
    """Fake provider that streams interim transcripts and returns its own result once stopped."""

    supports_interim_results = True
    stop_grace_seconds = 2.0

    def __init__(self, interims, result=None):
        self.interims = list(interims)  # (transcript, is_final, seconds before it)
        self.result = result or NLUResult(transcript="provider result", intent="provider_intent")
        self.stopped = threading.Event()
        self.on_interim_args = []
        self.finished = threading.Event()

    def listen(self, context=None, timeout=10.0, on_interim=None):
        self.on_interim_args.append(on_interim)
        self.stopped.clear()
        for transcript, is_final, delay in self.interims:
            time.sleep(delay)
            if on_interim is not None:
                on_interim(transcript, is_final)
        self.stopped.wait(timeout)
        time.sleep(0.05)  # the late result arrives a bit after the stop
        self.finished.set()
        return self.result

    def cancel(self):
        self.stopped.set()


def _make_orchestrator(provider, **config):
    # Skip __init__, which sets up logging and SIC services.
    orch = object.__new__(InteractionOrchestrator)
    orch.interaction_conf = InteractionConfig(signal_listening_behavior=False, **config)
    orch.nlu_provider = provider
    orch.logger = Mock()
    orch._log_queue = None
    orch.screen_provider = None
    orch.control = None
    return orch


YESNO = {"yes": ["ja"], "no": ["nee"]}


async def test_shortcut_returns_matched_intent_immediately():
    provider = StreamingProvider([("ja", False, 0.0)])
    orch = _make_orchestrator(provider, listen_settings={"ask_yesno": {"keyword_confirm_delay": 0.05}})

    start = time.monotonic()
    result = await orch.listen(timeout=5, listen_type="ask_yesno", keywords=YESNO)
    assert result == NLUResult(transcript="ja", intent="yes")
    assert time.monotonic() - start < 1
    assert provider.stopped.is_set()  # listening was stopped
    assert not provider.finished.is_set()  # without waiting for the provider's own result


async def test_final_transcript_is_accepted_without_confirm_delay():
    provider = StreamingProvider([("nee", True, 0.0)])
    orch = _make_orchestrator(provider, listen_settings={"ask_yesno": {"keyword_confirm_delay": 5}})

    result = await orch.listen(timeout=5, listen_type="ask_yesno", keywords=YESNO)
    assert result.intent == "no"


async def test_changed_transcript_cancels_match():
    # "ja" is followed by more words within the confirm delay, so the provider decides.
    provider = StreamingProvider([("ja", False, 0.0), ("ja maar eigenlijk niet", False, 0.05)])
    orch = _make_orchestrator(provider, listen_settings={"ask_yesno": {"keyword_confirm_delay": 0.3}})
    threading.Timer(0.5, provider.cancel).start()

    result = await orch.listen(timeout=5, listen_type="ask_yesno", keywords=YESNO)
    assert result == provider.result


async def test_repeated_transcript_does_not_restart_confirmation():
    # Dialogflow sends the same interim transcript several times; the confirmation keeps running.
    provider = StreamingProvider([("weet ik niet", False, 0.0)] + [("weet ik niet", False, 0.1)] * 5)
    orch = _make_orchestrator(provider, listen_settings={"ask_yesno": {"keyword_confirm_delay": 0.3}})

    start = time.monotonic()
    result = await orch.listen(timeout=5, listen_type="ask_yesno", keywords={"dontknow": ["weet ik niet"]})
    assert result.intent == "dontknow"
    assert time.monotonic() - start < 0.45  # confirmed 0.3 s after the first one, not after the last repeat


async def test_late_result_is_discarded_before_next_listen():
    provider = StreamingProvider([("ja", True, 0.0)])
    orch = _make_orchestrator(provider)
    assert (await orch.listen(timeout=5, listen_type="ask_yesno", keywords=YESNO)).intent == "yes"

    # The next listen first waits for the stopped one, then gets its own answer.
    provider.interims = [("nee", True, 0.0)]
    assert (await orch.listen(timeout=5, listen_type="ask_yesno", keywords=YESNO)).intent == "no"
    assert provider.finished.is_set()


@pytest.mark.parametrize("config,listen_settings", [
    ({"keyword_shortcut": False}, None),
    ({"listen_settings": {"ask_yesno": {"keyword_shortcut": False}}}, None),
    ({}, {"keyword_shortcut": False}),
])
async def test_shortcut_can_be_turned_off(config, listen_settings):
    provider = StreamingProvider([("ja", True, 0.0)])
    orch = _make_orchestrator(provider, **config)
    threading.Timer(0.1, provider.cancel).start()

    result = await orch.listen(timeout=5, listen_type="ask_yesno", keywords=YESNO, listen_settings=listen_settings)
    assert result == provider.result
    assert provider.on_interim_args == [None]


async def test_no_shortcut_without_keywords_or_interim_support():
    provider = StreamingProvider([("ja", True, 0.0)])
    orch = _make_orchestrator(provider)
    threading.Timer(0.1, provider.cancel).start()
    assert await orch.listen(timeout=5, listen_type="ask_open") == provider.result

    plain = Mock(spec=["listen", "cancel"])
    plain.listen.return_value = NLUResult(transcript="ja", intent=None)
    orch = _make_orchestrator(plain)
    assert await orch.listen(timeout=5, listen_type="ask_yesno", keywords=YESNO) == plain.listen.return_value
    assert "on_interim" not in plain.listen.call_args.kwargs
