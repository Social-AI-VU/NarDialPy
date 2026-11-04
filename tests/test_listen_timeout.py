"""Tests for the general listen timeout and per-move overrides."""
import importlib
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from nardial.interaction_orchestrator import InteractionConfig, InteractionOrchestrator
from nardial.mini_dialogs import MiniDialog
from nardial.providers.nlu import NLUResult


# ---------------------------------------------------------------------------
# InteractionConfig / InteractionOrchestrator.listen
# ---------------------------------------------------------------------------

def test_interaction_config_listen_timeout_default():
    assert InteractionConfig().listen_timeout == 10


def _make_orchestrator(listen_timeout):
    # Skip __init__, which sets up logging and SIC services.
    orch = object.__new__(InteractionOrchestrator)
    orch.interaction_conf = InteractionConfig(listen_timeout=listen_timeout, signal_listening_behavior=False)
    orch.nlu_provider = Mock()
    orch.nlu_provider.listen.return_value = NLUResult(transcript="", intent=None)
    return orch


async def test_listen_uses_general_timeout_when_none_given():
    orch = _make_orchestrator(listen_timeout=7)
    await orch.listen()
    assert orch.nlu_provider.listen.call_args.kwargs["timeout"] == 7


async def test_listen_explicit_timeout_overrides_general():
    orch = _make_orchestrator(listen_timeout=7)
    await orch.listen(timeout=20)
    assert orch.nlu_provider.listen.call_args.kwargs["timeout"] == 20


# ---------------------------------------------------------------------------
# Move handlers pass the move's timeout (or nothing) to the agent
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("move_type,handler,agent_method,extra", [
    ("ask_open", "handle_move_ask_open", "ask_open", {}),
    ("ask_yesno", "handle_move_ask_yesno", "ask_yesno", {}),
    ("ask_options", "handle_move_ask_options", "ask_options", {"options": ["a", "b"]}),
])
async def test_move_timeout_is_passed(make_mock_agent, session_history, topics_of_interest, user_model,
                                      move_type, handler, agent_method, extra):
    agent = make_mock_agent()
    md = MiniDialog('test', moves=[])
    md.set_conversation_config(agent, session_history, topics_of_interest, user_model)

    await getattr(md, handler)({"type": move_type, "text": "Q?", "timeout": 20, **extra})
    assert getattr(agent, agent_method).call_args.kwargs["timeout"] == 20


@pytest.mark.parametrize("move_type,handler,agent_method,extra", [
    ("ask_open", "handle_move_ask_open", "ask_open", {}),
    ("ask_yesno", "handle_move_ask_yesno", "ask_yesno", {}),
    ("ask_options", "handle_move_ask_options", "ask_options", {"options": ["a", "b"]}),
])
async def test_move_without_timeout_uses_default(make_mock_agent, session_history, topics_of_interest, user_model,
                                                 move_type, handler, agent_method, extra):
    agent = make_mock_agent()
    md = MiniDialog('test', moves=[])
    md.set_conversation_config(agent, session_history, topics_of_interest, user_model)

    await getattr(md, handler)({"type": move_type, "text": "Q?", **extra})
    assert "timeout" not in getattr(agent, agent_method).call_args.kwargs


async def test_llm_exchange_without_duration_uses_default(make_mock_agent):
    agent = make_mock_agent(ask_llm_side_effect=["hello", "bye"])
    md = MiniDialog('test', moves=[])
    md.set_conversation_config(agent, [], [], {})

    await md._run_llm_exchange(prompt="p", max_turns=1, quit_phrases=[])
    assert agent.orchestrator.listen.call_args.kwargs["timeout"] is None


# ---------------------------------------------------------------------------
# DialogflowNLUProvider
# ---------------------------------------------------------------------------

class _StopListeningMessage:
    def __init__(self, session_id=0):
        self.session_id = session_id


@pytest.fixture
def dialogflow_provider(monkeypatch):
    """Import DialogflowNLUProvider against a stubbed SIC Dialogflow service."""
    connector = Mock()
    module = ModuleType("sic_framework.services.dialogflow.dialogflow")
    module.Dialogflow = Mock(return_value=connector)
    module.DialogflowConf = Mock()
    module.GetIntentRequest = Mock()
    module.StopListeningMessage = _StopListeningMessage
    monkeypatch.setitem(sys.modules, "sic_framework.services", ModuleType("sic_framework.services"))
    monkeypatch.setitem(sys.modules, "sic_framework.services.dialogflow", ModuleType("sic_framework.services.dialogflow"))
    monkeypatch.setitem(sys.modules, "sic_framework.services.dialogflow.dialogflow", module)
    monkeypatch.delitem(sys.modules, "nardial.providers.nlu.dialogflow", raising=False)

    provider_module = importlib.import_module("nardial.providers.nlu.dialogflow")
    return provider_module.DialogflowNLUProvider(conf=Mock()), connector


def test_dialogflow_stops_at_timeout_and_keeps_final_reply(dialogflow_provider):
    # Dialogflow only returns its final result after the stream is closed at the timeout.
    provider, connector = dialogflow_provider
    stopped = threading.Event()
    connector.send_message.side_effect = lambda msg: stopped.set()

    def request(_req, timeout):
        assert stopped.wait(timeout)
        query_result = SimpleNamespace(query_text="een draak")
        return SimpleNamespace(response=SimpleNamespace(query_result=query_result), intent=None)

    connector.request.side_effect = request

    assert provider.listen(timeout=0.05) == NLUResult(transcript="een draak", intent=None)
    stop = connector.send_message.call_args.args[0]
    assert isinstance(stop, _StopListeningMessage)
    assert stop.session_id == provider._request_id


def test_dialogflow_waits_grace_period_after_timeout(dialogflow_provider):
    provider, connector = dialogflow_provider
    connector.request.side_effect = TimeoutError("timed out")

    assert provider.listen(timeout=5) == NLUResult(transcript="", intent=None)
    assert connector.request.call_args.kwargs["timeout"] == 5 + provider.stop_grace_seconds


def test_dialogflow_no_stop_when_reply_arrives_before_timeout(dialogflow_provider):
    provider, connector = dialogflow_provider
    connector.request.return_value = SimpleNamespace(response={}, intent=None)

    provider.listen(timeout=0.05)
    time.sleep(0.1)
    connector.send_message.assert_not_called()


def test_dialogflow_reply_without_query_result_is_empty(dialogflow_provider):
    provider, connector = dialogflow_provider
    connector.request.return_value = SimpleNamespace(response={}, intent=None)

    assert provider.listen(timeout=5) == NLUResult(transcript="", intent=None)
    connector.send_message.assert_not_called()


def test_dialogflow_reply_with_query_result(dialogflow_provider):
    provider, connector = dialogflow_provider
    query_result = SimpleNamespace(query_text="yes please")
    connector.request.return_value = SimpleNamespace(
        response=SimpleNamespace(query_result=query_result), intent="answer_yes")

    assert provider.listen(timeout=5) == NLUResult(transcript="yes please", intent="answer_yes")


def test_dialogflow_cancel_stops_service_listening(dialogflow_provider):
    provider, connector = dialogflow_provider
    provider.cancel()
    assert isinstance(connector.send_message.call_args.args[0], _StopListeningMessage)
