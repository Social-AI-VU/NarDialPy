import json
from unittest.mock import Mock

from nardial.conversation_state import ConversationState


def test_persists_only_in_participants_directory(tmp_path):
    state = ConversationState(base_dir=str(tmp_path), participant_id="alice", use_json_file=True)
    session_id = state.start_session(participant_id=state.participant_id, run_id="run_001")

    state.add_events(session_id, [{"type": "dialog_start", "dialog_id": "greeting"}])
    state.end_session(session_id, completed_ids=["greeting"], topics_of_interest=["music"])
    state.save()

    participant_file = tmp_path / "participants" / "alice.json"
    assert participant_file.exists()
    assert (tmp_path / "conversation_state.json").exists()

    with open(participant_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["summary"]["dialog_ids_seen"] == ["greeting"]


def test_loads_and_extends_state_from_participant_file(tmp_path):
    first = ConversationState(base_dir=str(tmp_path), participant_id="alice", use_json_file=True)
    sid1 = first.start_session(participant_id=first.participant_id, run_id="run_001")
    first.end_session(sid1, completed_ids=["greeting"], topics_of_interest=["music"])
    first.save()

    second = ConversationState(base_dir=str(tmp_path), participant_id="alice", use_json_file=True)
    assert "greeting" in second.completed_dialogs
    assert "music" in second.topics_of_interest
    # Session transcript history is not auto-loaded into in-memory sessions on init.
    assert len(second.sessions) == 0

    sid2 = second.start_session(participant_id=second.participant_id, run_id="run_002")
    assert sid2 == "sess_0001"


def test_persists_and_reloads_when_participant_id_is_none(tmp_path):
    state = ConversationState(base_dir=str(tmp_path), participant_id=None, use_json_file=True)
    session_id = state.start_session(run_id="run_001")
    state.end_session(session_id, completed_ids=["intro"], topics_of_interest=["art"])
    state.save()

    participant_file = tmp_path / "participants" / "__unknown__.json"
    assert participant_file.exists()
    assert (tmp_path / "conversation_state.json").exists()
    with open(participant_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["participant_id"] == "__unknown__"

    reloaded = ConversationState(base_dir=str(tmp_path), participant_id=None, use_json_file=True)
    # With participant_id=None, continuity is written to __unknown__.json but not auto-restored.
    assert reloaded.completed_dialogs == []
    assert reloaded.topics_of_interest == []
    assert len(reloaded.sessions) == 0


def _seed_three_sessions(tmp_path):
    """Three ended sessions for participant 'alice', all recorded on one
    ConversationState instance (self.sessions accumulates across
    start_session() calls on the same instance -- see
    test_loads_and_extends_state_from_participant_file's "not auto-loaded on
    init" note above: a *fresh* instance's self.sessions always starts empty,
    so multi-session history has to be built this way to end up on disk)."""
    state = ConversationState(base_dir=str(tmp_path), participant_id="alice")
    sid1 = state.start_session(participant_id="alice", run_id="run_1")
    state.end_session(sid1, completed_ids=["d1", "d2"], topics_of_interest=["music"])

    sid2 = state.start_session(participant_id="alice", run_id="run_2")
    state.end_session(sid2, completed_ids=["d3"], topics_of_interest=["art"])

    sid3 = state.start_session(participant_id="alice", run_id="run_3")
    state.end_session(sid3, completed_ids=["d4"], topics_of_interest=["sports"])
    return state


def test_count_completed_sessions_reads_persisted_transcript(tmp_path):
    _seed_three_sessions(tmp_path)

    fresh = ConversationState(base_dir=str(tmp_path), participant_id="alice")
    assert fresh.count_completed_sessions() == 3


def test_count_completed_sessions_excludes_a_session_still_in_progress(tmp_path):
    state = _seed_three_sessions(tmp_path)
    sid4 = state.start_session(participant_id="alice", run_id="run_4")
    state.add_dialog_id(sid4, "d5")
    # Simulate a crash: flush to disk without ever calling end_session().
    state.save_participant_transcript(state.participant_id)

    fresh = ConversationState(base_dir=str(tmp_path), participant_id="alice")
    assert fresh.count_completed_sessions() == 3


def test_count_completed_sessions_is_zero_for_unknown_participant(tmp_path):
    state = ConversationState(base_dir=str(tmp_path), participant_id="nobody")
    assert state.count_completed_sessions() == 0


def test_truncate_from_session_keeps_earlier_sessions_and_recomputes_continuity(tmp_path):
    _seed_three_sessions(tmp_path)

    fresh = ConversationState(base_dir=str(tmp_path), participant_id="alice")
    fresh.truncate_from_session(2)

    assert set(fresh.completed_dialogs) == {"d1", "d2"}
    assert fresh.topics_of_interest == ["music"]
    assert [s.session_id for s in fresh.sessions] == ["sess_0001"]

    with open(tmp_path / "participants" / "alice.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["dialog_ids"] == ["d1", "d2"]


def test_truncate_from_session_calls_save_continuity(tmp_path, monkeypatch):
    _seed_three_sessions(tmp_path)

    fresh = ConversationState(base_dir=str(tmp_path), participant_id="alice")
    spy = Mock(wraps=fresh.user_model.save_continuity)
    monkeypatch.setattr(fresh.user_model, "save_continuity", spy)

    fresh.truncate_from_session(2)

    spy.assert_called_once_with(completed_dialogs=["d1", "d2"], topics_of_interest=["music"])
