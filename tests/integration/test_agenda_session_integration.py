import json

import pytest

from nardial.agenda.session_plan import SessionPlan, SessionTemplate
from nardial.session_manager import SessionManager
from nardial.user_model import UserModel

GREETING_DOC = {
    "id": "greeting_1",
    "type": "functional",
    "functional_type": "greeting",
    "moves": [{"type": "say", "text": "Hello!"}],
}
FAREWELL_DOC = {
    "id": "farewell_1",
    "type": "functional",
    "functional_type": "farewell",
    "moves": [{"type": "say", "text": "Bye!"}],
}
NARRATIVE_STEP1_DOC = {
    "id": "step_1",
    "type": "narrative",
    "thread": "thread_a",
    "position": 1,
    "moves": [{"type": "say", "text": "Step 1"}],
}
NARRATIVE_STEP2_DOC = {
    "id": "step_2",
    "type": "narrative",
    "thread": "thread_a",
    "position": 2,
    "moves": [{"type": "say", "text": "Step 2"}],
}
CHITCHAT_DOC = {
    "id": "chitchat_1",
    "type": "chitchat",
    "topics": ["pizza"],
    "moves": [{"type": "say", "text": "Pizza chat"}],
}
LLM_DOC = {
    "id": "llm_1",
    "type": "llm_based",
    "prompt": "Chat about pizza.",
    "max_turns": 1,
    "moves": [],
}


def write_dialog_json(tmp_path, docs, filename="dialogs.json"):
    path = tmp_path / filename
    path.write_text(json.dumps(docs), encoding="utf-8")
    return str(path)


def say_texts(agent):
    return [call.args[0] for call in agent.say.call_args_list]


@pytest.fixture
def shared_continuity_store(monkeypatch):
    """Simulate a persistent (e.g. Redis-backed) continuity store shared across
    separate UserModel/ConversationState instances, the way a real datastore
    would behave in production. Unit tests stub Redis out entirely (see
    conftest.no_redis_connections), so without this, every fresh
    ConversationState/SessionManager gets a UserModel with an empty in-memory
    cache and cross-session participant continuity can never be observed.
    """
    store: dict = {}

    def get_completed_dialogs(self):
        return list(store.get(self._pid, {}).get("completed_dialogs", []))

    def get_topics_of_interest(self):
        return list(store.get(self._pid, {}).get("topics_of_interest", []))

    def save_continuity(self, completed_dialogs, topics_of_interest):
        entry = store.setdefault(self._pid, {})
        entry["completed_dialogs"] = list(completed_dialogs)
        entry["topics_of_interest"] = list(topics_of_interest)

    monkeypatch.setattr(UserModel, "get_completed_dialogs", get_completed_dialogs)
    monkeypatch.setattr(UserModel, "get_topics_of_interest", get_topics_of_interest)
    monkeypatch.setattr(UserModel, "save_continuity", save_continuity)
    return store


def test_full_mixed_agenda_run_persists_correct_conversation_state(tmp_path, monkeypatch, make_mock_agent):
    monkeypatch.chdir(tmp_path)
    dialog_path = write_dialog_json(
        tmp_path,
        [GREETING_DOC, FAREWELL_DOC, NARRATIVE_STEP1_DOC, NARRATIVE_STEP2_DOC, CHITCHAT_DOC, LLM_DOC],
    )
    agent = make_mock_agent()

    manager = SessionManager(
        session_agenda=[
            "greeting_1",
            {"type": "narrative_slot", "thread": "thread_a", "bounds": {"count_min": 2, "count_max": 2}},
            {"type": "chitchat_slot"},
            {"type": "llm_dialog_ref", "id": "llm_1"},
            "farewell_1",
        ],
        agent=agent,
        dialog_json_path=dialog_path,
        participant_id="p_integration_full",
    )
    manager.run()

    assert say_texts(agent) == ["Hello!", "Step 1", "Step 2", "Pizza chat", "Bye!"]
    assert set(manager.conversation_state.completed_dialogs) == {
        "greeting_1", "step_1", "step_2", "chitchat_1", "llm_1", "farewell_1",
    }

    participant_file = tmp_path / "participants" / "p_integration_full.json"
    assert participant_file.exists()
    with open(participant_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data["sessions"]) == 1
    session = data["sessions"][0]
    assert session["ended_at"] is not None
    assert session["dialog_ids"] == ["greeting_1", "step_1", "step_2", "chitchat_1", "llm_1", "farewell_1"]


def test_second_session_excludes_already_completed_narrative_dialogs(
    tmp_path, monkeypatch, make_mock_agent, shared_continuity_store
):
    """End-to-end ExcludeIfSeenRule(scope=PARTICIPANT) check: a NarrativeDialog
    completed by an earlier session for this participant must not be offered
    again by a fresh SessionManager instance."""
    monkeypatch.chdir(tmp_path)
    dialog_path = write_dialog_json(tmp_path, [NARRATIVE_STEP1_DOC, NARRATIVE_STEP2_DOC])

    agent1 = make_mock_agent()
    manager1 = SessionManager(
        session_agenda=[{"type": "narrative_slot", "thread": "thread_a", "bounds": {"count_min": 2, "count_max": 2}}],
        agent=agent1,
        dialog_json_path=dialog_path,
        participant_id="p_integration_exclude",
    )
    manager1.run()
    assert say_texts(agent1) == ["Step 1", "Step 2"]

    agent2 = make_mock_agent()
    manager2 = SessionManager(
        session_agenda=[{"type": "narrative_slot", "thread": "thread_a"}],
        agent=agent2,
        dialog_json_path=dialog_path,
        participant_id="p_integration_exclude",
    )
    manager2.run()

    assert say_texts(agent2) == []
    assert set(manager2.conversation_state.completed_dialogs) == {"step_1", "step_2"}


def test_session_plan_driven_run_selects_different_templates_per_session(tmp_path, monkeypatch, make_mock_agent):
    """Two-session SessionPlan-driven run: the same SessionManager instance
    is advanced to a second session (the same way test_session_manager.py's
    off-by-one regression test simulates prior sessions), and the plan must
    select each session's own template."""
    monkeypatch.chdir(tmp_path)
    session1_doc = {**GREETING_DOC, "id": "session_1_dialog"}
    session2_doc = {**FAREWELL_DOC, "id": "session_2_dialog"}
    dialog_path = write_dialog_json(tmp_path, [session1_doc, session2_doc])

    plan = SessionPlan(
        plan_id="two_session_plan",
        sessions=[
            SessionTemplate(session_index=1, agenda=["session_1_dialog"]),
            SessionTemplate(session_index=2, agenda=["session_2_dialog"]),
        ],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")

    agent = make_mock_agent()
    manager = SessionManager(
        session_agenda=[],
        agent=agent,
        dialog_json_path=dialog_path,
        participant_id="p_integration_plan",
        session_plan_path=str(plan_path),
    )
    assert manager.session_agenda == ["session_1_dialog"]

    manager.run()
    assert say_texts(agent) == ["Hello!"]

    # Advance to session 2 for the same participant/manager.
    manager.conversation_state.start_session(
        participant_id=manager.conversation_state.participant_id, run_id="run_2"
    )
    resolved = manager._resolve_session_plan_agenda()
    assert resolved == ["session_2_dialog"]
    manager.session_agenda = resolved
    manager.session_id = manager.conversation_state.sessions[-1].session_id

    manager.run()
    assert say_texts(agent) == ["Hello!", "Bye!"]
