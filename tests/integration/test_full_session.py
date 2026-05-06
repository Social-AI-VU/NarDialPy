"""Integration tests for a full SessionManager run.

These tests exercise the complete session lifecycle:
  - loading dialogs from a real JSON file
  - running each dialog against a mocked ConversationAgent
  - verifying that session history, completed dialogs, and participant
    transcripts are written correctly to disk

No Redis or SIC services are required; the ``redirect_cwd`` fixture routes
all file writes to a temp directory.

Run with::

    pytest tests/integration/test_full_session.py --integration
"""
import json
import pytest
from unittest.mock import Mock

from nardial.session_manager import SessionManager


# ── Dialog fixtures ───────────────────────────────────────────────────────────

DIALOGS = [
    {
        "id": "greeting",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [
            {"type": "say", "text": "Hello, nice to meet you!"},
            {"type": "ask_open", "text": "What is your name?", "set_variable": "name"},
        ],
    },
    {
        "id": "activity",
        "type": "narrative",
        "thread": "main",
        "position": 1,
        "moves": [
            {"type": "ask_yesno", "text": "Do you like outdoor activities?", "set_variable": "likes_outdoors"},
            {"type": "say", "text": "Great, let me tell you more!"},
        ],
    },
    {
        "id": "farewell",
        "type": "functional",
        "functional_type": "farewell",
        "moves": [{"type": "say", "text": "Goodbye!"}],
    },
]


@pytest.fixture
def dialogs_file(tmp_path):
    path = tmp_path / "dialogs.json"
    path.write_text(json.dumps(DIALOGS))
    return str(path)


@pytest.fixture
def mock_agent():
    agent = Mock()
    agent.say = Mock()
    agent.ask_yesno = Mock(return_value="yes")
    agent.ask_open = Mock(return_value="My name is Alice")
    agent.ask_options = Mock(return_value=None)
    agent.extract_topics_with_llm = Mock(return_value=["outdoors"])
    return agent


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestFullSessionRun:
    def test_all_agenda_dialogs_complete(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=["greeting", "activity", "farewell"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
            participant_id="alice",
        )
        sm.run()

        completed = set(sm.conversation_state.completed_dialogs)
        assert "greeting" in completed
        assert "activity" in completed
        assert "farewell" in completed

    def test_say_moves_called_in_order(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=["greeting", "farewell"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        sm.run()
        spoken = [c.args[0] for c in mock_agent.say.call_args_list]
        assert spoken[0] == "Hello, nice to meet you!"
        assert spoken[-1] == "Goodbye!"

    def test_set_variable_propagated_to_user_model(self, dialogs_file, mock_agent):
        """Variables set by ask_open moves should persist in the user model."""
        mock_agent.ask_open = Mock(return_value="'Alice'")
        sm = SessionManager(
            session_agenda=["greeting"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
            participant_id="alice",
        )
        sm.run()
        # extract_open_value picks the quoted token "Alice"
        assert sm.conversation_state.user_model.get("name") == "Alice"

    def test_participant_transcript_written_to_disk(self, dialogs_file, mock_agent, tmp_path):
        sm = SessionManager(
            session_agenda=["greeting"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
            participant_id="alice",
        )
        sm.run()
        transcript_file = tmp_path / "participants" / "alice.json"
        assert transcript_file.exists()
        data = json.loads(transcript_file.read_text())
        assert data["participant_id"] == "alice"

    def test_session_history_contains_dialog_markers(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=["greeting"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        sm.run()

        # Retrieve the session events from the stored session
        session = sm.conversation_state.sessions[0]
        event_types = {e["type"] for e in session.events}
        assert "dialog_start" in event_types
        assert "dialog_end" in event_types

    def test_ineligible_dialog_does_not_run(self, dialogs_file, mock_agent):
        """A dialog that has already been completed should be skipped."""
        sm = SessionManager(
            session_agenda=["greeting"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        # Pre-mark greeting as completed
        sm.conversation_state.completed_dialogs.append("greeting")
        sm.run()
        mock_agent.say.assert_not_called()

    def test_empty_agenda_runs_all_dialogs(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=[],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        sm.run()
        # All three dialogs in the file should have completed
        assert len(sm.conversation_state.completed_dialogs) == 3
