"""Tests for SessionManager — dialog loading, session block construction, and run behaviour."""
import json
import pytest
from unittest.mock import Mock

from nardial.session_manager import SessionManager


# ── Shared fixtures ───────────────────────────────────────────────────────────

SIMPLE_DIALOGS = [
    {
        "id": "greeting",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [{"type": "say", "text": "Hello!"}],
    },
    {
        "id": "farewell",
        "type": "functional",
        "functional_type": "farewell",
        "moves": [{"type": "say", "text": "Goodbye!"}],
    },
    {
        "id": "chapter_1",
        "type": "narrative",
        "thread": "main",
        "position": 1,
        "moves": [{"type": "say", "text": "Chapter 1."}],
    },
]


@pytest.fixture(autouse=True)
def redirect_cwd(tmp_path, monkeypatch):
    """Route ConversationState file writes to a temp directory."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def dialogs_file(tmp_path):
    path = tmp_path / "dialogs.json"
    path.write_text(json.dumps(SIMPLE_DIALOGS))
    return str(path)


@pytest.fixture
def mock_agent():
    agent = Mock()
    agent.say = Mock()
    agent.ask_yesno = Mock(return_value="yes")
    agent.ask_open = Mock(return_value="some answer")
    agent.ask_options = Mock(return_value="option_a")
    agent.extract_topics_with_llm = Mock(return_value=[])
    return agent


@pytest.fixture
def session_manager(dialogs_file, mock_agent):
    return SessionManager(
        session_agenda=[],
        agent=mock_agent,
        dialog_json_path=dialogs_file,
    )


# ── load_dialogs_from_json ────────────────────────────────────────────────────

class TestLoadDialogsFromJson:
    def test_loads_all_dialogs_from_valid_file(self, dialogs_file):
        result = SessionManager.load_dialogs_from_json(dialogs_file)
        assert len(result) == 3

    def test_returns_empty_list_for_missing_file(self, tmp_path):
        result = SessionManager.load_dialogs_from_json(str(tmp_path / "missing.json"))
        assert result == []

    def test_returns_empty_list_for_invalid_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("this is not valid json {{{")
        result = SessionManager.load_dialogs_from_json(str(bad))
        assert result == []

    def test_returns_empty_list_when_dialogs_contain_validation_errors(self, tmp_path):
        invalid = tmp_path / "invalid.json"
        invalid.write_text(json.dumps([{"id": "x", "type": "unknown_type_xyz"}]))
        result = SessionManager.load_dialogs_from_json(str(invalid))
        assert result == []


# ── build_session_block ───────────────────────────────────────────────────────

class TestBuildSessionBlock:
    def test_empty_agenda_uses_all_dialogs(self, session_manager):
        assert len(session_manager.session_block) == len(session_manager.dialogs)

    def test_agenda_filters_to_requested_ids(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=["greeting"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        assert len(sm.session_block) == 1
        assert sm.session_block[0].dialog_id == "greeting"

    def test_agenda_preserves_order(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=["farewell", "greeting"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        ids = [d.dialog_id for d in sm.session_block]
        assert ids == ["farewell", "greeting"]

    def test_unknown_agenda_ids_silently_skipped(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=["nonexistent_dialog"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        assert sm.session_block == []


# ── run ───────────────────────────────────────────────────────────────────────

class TestRun:
    def test_run_calls_say_for_each_say_move(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=["greeting"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        sm.run()
        mock_agent.say.assert_called_with("Hello!")

    def test_run_marks_dialog_as_completed(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=["greeting"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        sm.run()
        assert "greeting" in sm.conversation_state.completed_dialogs

    def test_run_skips_already_completed_narrative_dialog(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=["chapter_1"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        # NarrativeDialog has ExcludeIfSeenRule — it must not run when completed.
        sm.conversation_state.completed_dialogs.append("chapter_1")
        sm.run()
        mock_agent.say.assert_not_called()

    def test_functional_dialog_runs_even_when_previously_completed(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=["greeting"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        # FunctionalDialog has no ExcludeIfSeenRule — greetings re-run each session.
        sm.conversation_state.completed_dialogs.append("greeting")
        sm.run()
        mock_agent.say.assert_called_with("Hello!")

    def test_run_executes_dialogs_in_agenda_order(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=["greeting", "farewell"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        sm.run()
        calls = [call.args[0] for call in mock_agent.say.call_args_list]
        assert calls == ["Hello!", "Goodbye!"]
