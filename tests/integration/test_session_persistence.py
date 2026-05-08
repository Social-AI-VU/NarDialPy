"""Integration tests for ConversationState file-based persistence.

These tests exercise the full write → reload cycle using real JSON files
on disk. No Redis or SIC services are required; the ``redirect_cwd``
fixture in this directory's conftest.py routes all writes to a temp dir.

Run with::

    pytest tests/integration/test_session_persistence.py --integration
"""
import pytest

from nardial.conversation_state import ConversationState


@pytest.fixture
def state(tmp_path):
    """A file-backed ConversationState rooted at a temp directory."""
    return ConversationState(
        base_dir=str(tmp_path),
        participant_id="alice",
        use_json_file=True,
    )


class TestSessionLifecycle:
    def test_start_session_returns_session_id(self, state):
        sid = state.start_session(participant_id="alice", run_id="run_001")
        assert sid.startswith("sess_")

    def test_end_session_writes_participant_file(self, state, tmp_path):
        sid = state.start_session(participant_id="alice", run_id="run_001")
        state.end_session(sid, completed_ids=["greeting"], topics_of_interest=["cats"])
        participant_file = tmp_path / "participants" / "alice.json"
        assert participant_file.exists()

    def test_completed_dialogs_persisted_in_participant_file(self, state, tmp_path):
        sid = state.start_session(participant_id="alice", run_id="run_001")
        state.end_session(sid, completed_ids=["d1", "d2"])
        import json
        data = json.loads((tmp_path / "participants" / "alice.json").read_text())
        seen = data["summary"]["dialog_ids_seen"]
        assert "d1" in seen and "d2" in seen

    def test_topics_of_interest_persisted(self, state, tmp_path):
        sid = state.start_session(participant_id="alice", run_id="run_001")
        state.end_session(sid, topics_of_interest=["dogs", "hiking"])
        import json
        data = json.loads((tmp_path / "participants" / "alice.json").read_text())
        topics = data["summary"]["topics_of_interest"]
        assert "dogs" in topics and "hiking" in topics


class TestContinuityAcrossSessions:
    def test_completed_dialogs_accumulated_across_sessions(self, tmp_path):
        """Completed dialog IDs from multiple sessions are merged in the summary."""
        # First session
        s1 = ConversationState(base_dir=str(tmp_path), participant_id="bob", use_json_file=True)
        sid1 = s1.start_session(participant_id="bob", run_id="run_001")
        s1.end_session(sid1, completed_ids=["greeting"])

        # Second session — reloads from the participant file
        s2 = ConversationState(base_dir=str(tmp_path), participant_id="bob", use_json_file=True)
        sid2 = s2.start_session(participant_id="bob", run_id="run_002")
        s2.end_session(sid2, completed_ids=["farewell"])

        import json
        data = json.loads((tmp_path / "participants" / "bob.json").read_text())
        seen = set(data["summary"]["dialog_ids_seen"])
        assert "greeting" in seen
        assert "farewell" in seen

    def test_anonymous_participant_uses_unknown_filename(self, tmp_path):
        """With participant_id=None the file is named __unknown__.json."""
        s = ConversationState(base_dir=str(tmp_path), participant_id=None, use_json_file=True)
        sid = s.start_session(run_id="run_anon")
        s.end_session(sid)
        assert (tmp_path / "participants" / "__unknown__.json").exists()

    def test_session_events_stored_in_transcript(self, tmp_path):
        s = ConversationState(base_dir=str(tmp_path), participant_id="carol", use_json_file=True)
        sid = s.start_session(participant_id="carol", run_id="run_001")
        events = [
            {"role": "system", "type": "dialog_start", "dialog_id": "greeting"},
            {"role": "robot", "type": "say", "text": "Hello!"},
            {"role": "system", "type": "dialog_end", "dialog_id": "greeting"},
        ]
        s.add_events(sid, events)
        s.end_session(sid)

        import json
        data = json.loads((tmp_path / "participants" / "carol.json").read_text())
        stored_events = data["sessions"][0]["events"]
        assert len(stored_events) == 3
        assert stored_events[1]["text"] == "Hello!"
