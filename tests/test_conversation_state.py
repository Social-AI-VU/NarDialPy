import json

from nardial.conversation_state import ConversationState


def test_persists_only_in_participants_directory(tmp_path):
    state = ConversationState(base_dir=str(tmp_path), participant_id="alice")
    session_id = state.start_session(participant_id=state.participant_id, run_id="run_001")

    state.add_events(session_id, [{"type": "dialog_start", "dialog_id": "greeting"}])
    state.end_session(session_id, completed_ids=["greeting"], topics_of_interest=["music"])
    state.save()

    participant_file = tmp_path / "participants" / "alice.json"
    assert participant_file.exists()
    assert not (tmp_path / "conversation_state.json").exists()

    with open(participant_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["summary"]["dialog_ids_seen"] == ["greeting"]


def test_loads_and_extends_state_from_participant_file(tmp_path):
    first = ConversationState(base_dir=str(tmp_path), participant_id="alice")
    sid1 = first.start_session(participant_id=first.participant_id, run_id="run_001")
    first.end_session(sid1, completed_ids=["greeting"], topics_of_interest=["music"])
    first.save()

    second = ConversationState(base_dir=str(tmp_path), participant_id="alice")
    assert "greeting" in second.completed_dialogs
    assert "music" in second.topics_of_interest
    assert len(second.sessions) == 1

    sid2 = second.start_session(participant_id=second.participant_id, run_id="run_002")
    assert sid2 == "sess_0002"


def test_persists_and_reloads_when_participant_id_is_none(tmp_path):
    state = ConversationState(base_dir=str(tmp_path), participant_id=None)
    session_id = state.start_session(run_id="run_001")
    state.end_session(session_id, completed_ids=["intro"], topics_of_interest=["art"])
    state.save()

    participant_file = tmp_path / "participants" / "__unknown__.json"
    assert participant_file.exists()
    assert not (tmp_path / "conversation_state.json").exists()
    with open(participant_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["participant_id"] == "__unknown__"

    reloaded = ConversationState(base_dir=str(tmp_path), participant_id=None)
    assert "intro" in reloaded.completed_dialogs
    assert "art" in reloaded.topics_of_interest
    assert len(reloaded.sessions) == 1
