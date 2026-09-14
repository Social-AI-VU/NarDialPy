import json

from nardial.session_manager import SessionManager

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


def write_dialog_json(tmp_path, docs, filename="dialogs.json"):
    path = tmp_path / filename
    path.write_text(json.dumps(docs), encoding="utf-8")
    return str(path)


def say_texts(agent):
    return [call.args[0] for call in agent.say.call_args_list]


def test_plain_string_agenda_runs_dialogs_in_order(tmp_path, monkeypatch, make_mock_agent):
    monkeypatch.chdir(tmp_path)
    dialog_path = write_dialog_json(tmp_path, [GREETING_DOC, FAREWELL_DOC])
    agent = make_mock_agent()

    manager = SessionManager(
        session_agenda=["greeting_1", "farewell_1"],
        agent=agent,
        dialog_json_path=dialog_path,
        participant_id="p_plain_agenda",
    )
    manager.run()

    assert say_texts(agent) == ["Hello!", "Bye!"]
    assert set(manager.conversation_state.completed_dialogs) == {"greeting_1", "farewell_1"}


def test_empty_agenda_runs_all_loaded_dialogs_in_loaded_order(tmp_path, monkeypatch, make_mock_agent):
    """Regression: some demos (e.g. demo_dialog_with_characters_*.py) pass
    session_agenda=[] and rely on it running every loaded dialog."""
    monkeypatch.chdir(tmp_path)
    dialog_path = write_dialog_json(tmp_path, [GREETING_DOC, FAREWELL_DOC])
    agent = make_mock_agent()

    manager = SessionManager(
        session_agenda=[],
        agent=agent,
        dialog_json_path=dialog_path,
        participant_id="p_empty_agenda",
    )
    manager.run()

    assert say_texts(agent) == ["Hello!", "Bye!"]


def test_mixed_string_and_dict_agenda_resolves_end_to_end(tmp_path, monkeypatch, make_mock_agent):
    monkeypatch.chdir(tmp_path)
    dialog_path = write_dialog_json(
        tmp_path, [GREETING_DOC, NARRATIVE_STEP1_DOC, NARRATIVE_STEP2_DOC, CHITCHAT_DOC]
    )
    agent = make_mock_agent()

    manager = SessionManager(
        session_agenda=[
            "greeting_1",
            {"type": "narrative_slot", "thread": "thread_a"},
            {"type": "chitchat_slot"},
        ],
        agent=agent,
        dialog_json_path=dialog_path,
        participant_id="p_mixed_agenda",
    )
    manager.run()

    assert say_texts(agent) == ["Hello!", "Step 1", "Pizza chat"]
    assert set(manager.conversation_state.completed_dialogs) == {"greeting_1", "step_1", "chitchat_1"}


def test_constructor_stores_new_params_without_acting_on_them(tmp_path, monkeypatch, make_mock_agent):
    monkeypatch.chdir(tmp_path)
    dialog_path = write_dialog_json(tmp_path, [GREETING_DOC])
    agent = make_mock_agent()

    manager = SessionManager(
        session_agenda=["greeting_1"],
        agent=agent,
        dialog_json_path=dialog_path,
        participant_id="p_ctor_stubs",
        session_plan_path="unused_plan.json",
        session_index=3,
        reset_history_from_session=1,
        resume=True,
    )

    assert manager.session_plan_path == "unused_plan.json"
    assert manager.session_index == 3
    assert manager.reset_history_from_session == 1
    assert manager.resume is True


def test_default_new_params_are_inert(tmp_path, monkeypatch, make_mock_agent):
    monkeypatch.chdir(tmp_path)
    dialog_path = write_dialog_json(tmp_path, [GREETING_DOC])
    agent = make_mock_agent()

    manager = SessionManager(
        session_agenda=["greeting_1"],
        agent=agent,
        dialog_json_path=dialog_path,
        participant_id="p_ctor_defaults",
    )

    assert manager.session_plan_path is None
    assert manager.session_index is None
    assert manager.reset_history_from_session is None
    assert manager.resume is False
