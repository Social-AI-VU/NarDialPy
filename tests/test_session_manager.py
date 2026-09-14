import json

from nardial.agenda.session_plan import SessionPlan, SessionTemplate
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


def test_current_session_number_does_not_double_count_the_just_started_session(tmp_path, monkeypatch, make_mock_agent):
    """Regression: start_session() already appended the current session before
    _current_session_number() ever runs, so len(sessions) must NOT get +1'd."""
    monkeypatch.chdir(tmp_path)
    dialog_path = write_dialog_json(tmp_path, [GREETING_DOC])
    agent = make_mock_agent()

    manager = SessionManager(
        session_agenda=["greeting_1"],
        agent=agent,
        dialog_json_path=dialog_path,
        participant_id="p_session_number",
    )

    assert manager._current_session_number() == 1

    manager.conversation_state.start_session(participant_id="p_session_number", run_id="run_2")
    manager.conversation_state.start_session(participant_id="p_session_number", run_id="run_3")

    assert manager._current_session_number() == 3


def test_session_plan_path_picks_template_for_current_session_number(tmp_path, monkeypatch, make_mock_agent):
    monkeypatch.chdir(tmp_path)
    dialog_path = write_dialog_json(tmp_path, [GREETING_DOC, FAREWELL_DOC])

    plan = SessionPlan(
        plan_id="onboarding",
        sessions=[
            SessionTemplate(session_index=1, agenda=["greeting_1"]),
            SessionTemplate(session_index=2, agenda=["farewell_1"]),
        ],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")

    agent = make_mock_agent()
    manager = SessionManager(
        session_agenda=["farewell_1"],  # would prove the plan was never applied if this ran instead
        agent=agent,
        dialog_json_path=dialog_path,
        participant_id="p_session_plan",
        session_plan_path=str(plan_path),
    )

    assert manager.session_agenda == ["greeting_1"]

    manager.run()

    assert say_texts(agent) == ["Hello!"]


def test_session_plan_path_uses_correct_template_after_simulated_prior_sessions(tmp_path, monkeypatch, make_mock_agent):
    """Off-by-one regression: a naive len(sessions) + 1 would land on the
    wrong exact-match template once a prior session is already recorded."""
    monkeypatch.chdir(tmp_path)
    dialog_path = write_dialog_json(tmp_path, [GREETING_DOC])

    plan = SessionPlan(
        plan_id="onboarding",
        sessions=[
            SessionTemplate(session_index=1, agenda=["session_1_agenda"]),
            SessionTemplate(session_index=2, agenda=["session_2_agenda"]),
            SessionTemplate(session_index=3, agenda=["session_3_agenda"]),
        ],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")

    agent = make_mock_agent()
    manager = SessionManager(
        session_agenda=[],
        agent=agent,
        dialog_json_path=dialog_path,
        participant_id="p_session_plan_offbyone",
        session_plan_path=str(plan_path),
    )
    assert manager.session_agenda == ["session_1_agenda"]  # this session is session_number == 1

    # Simulate that one earlier session for this participant already
    # happened before this SessionManager's session started.
    manager.conversation_state.sessions.insert(0, manager.conversation_state.sessions[0])
    assert manager._current_session_number() == 2

    resolved = manager._resolve_session_plan_agenda()

    assert resolved == ["session_2_agenda"]


def test_session_plan_path_falls_back_to_given_agenda_when_plan_missing(tmp_path, monkeypatch, make_mock_agent):
    monkeypatch.chdir(tmp_path)
    dialog_path = write_dialog_json(tmp_path, [GREETING_DOC])
    agent = make_mock_agent()

    manager = SessionManager(
        session_agenda=["greeting_1"],
        agent=agent,
        dialog_json_path=dialog_path,
        participant_id="p_session_plan_missing",
        session_plan_path=str(tmp_path / "does_not_exist.json"),
    )

    assert manager.session_agenda == ["greeting_1"]
