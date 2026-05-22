from types import SimpleNamespace
from unittest.mock import Mock

from nardial.interaction_orchestrator import InteractionOrchestrator


def _bare_orchestrator(**config_kw):
    conf = SimpleNamespace(summarize_every_n_exchanges=config_kw.pop("summarize_every_n_exchanges", None))
    conf.__dict__.update(config_kw)
    orch = InteractionOrchestrator.__new__(InteractionOrchestrator)
    orch.interaction_conf = conf
    orch.reset_rolling_conversation_summary()
    orch.transcript_append = Mock()
    return orch


def _history_with_n_users(n: int):
    history = [{"role": "robot", "text": "Hello detective."}]
    for i in range(1, n + 1):
        history.append({"role": "user", "text": f"Question {i}?"})
        history.append({"role": "robot", "text": f"Answer {i}."})
    return history


def test_rolling_summary_triggers_on_tenth_user_exchange():
    orch = _bare_orchestrator(summarize_every_n_exchanges=10)
    summaries = []

    def fake_gpt(**kwargs):
        summaries.append(kwargs.get("user_prompt", ""))
        return f"Summary through chunk {len(summaries)}"

    orch.request_from_gpt = Mock(side_effect=fake_gpt)

    history = _history_with_n_users(10)
    ctx = orch.reconstruct_conversation(history)

    assert len(summaries) == 1
    assert orch._summarized_through_exchange == 10
    assert len(ctx) == 1
    assert ctx[0].startswith("system: [Summary of earlier conversation]")
    assert "Summary through chunk 1" in ctx[0]


def test_rolling_summary_keeps_recent_verbatim_after_summarizing():
    orch = _bare_orchestrator(summarize_every_n_exchanges=10)
    orch.request_from_gpt = Mock(return_value="Earlier plot points.")
    orch._summarized_through_exchange = 10
    orch._rolling_conversation_summary = "Earlier plot points."

    history = _history_with_n_users(12)
    ctx = orch.reconstruct_conversation(history, max_items=12)

    assert ctx[0].startswith("system: [Summary of earlier conversation]")
    assert "user: Question 11?" in ctx
    assert "user: Question 12?" in ctx
    assert "user: Question 1?" not in ctx


def test_no_summary_when_interval_unset():
    orch = _bare_orchestrator(summarize_every_n_exchanges=None)
    orch.request_from_gpt = Mock()

    history = _history_with_n_users(15)
    ctx = orch.reconstruct_conversation(history, max_items=4)

    orch.request_from_gpt.assert_not_called()
    assert ctx[0] == "user: Question 14?"
    assert len(ctx) == 4
