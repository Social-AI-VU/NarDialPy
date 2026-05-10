"""Tests for SessionManager — dialog loading, registry building, and run behaviour."""
import json
import pytest
from unittest.mock import Mock, patch

from nardial.conversation_state import ConversationState
from nardial.dialog_registry import DialogRegistry
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


# ── load_dialog_registry / DialogRegistry ────────────────────────────────────

class TestDialogRegistry:
    def test_registry_built_from_valid_file(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=[],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        assert isinstance(sm._registry, DialogRegistry)
        assert len(sm._registry) == 3

    def test_registry_contains_all_loaded_dialogs(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=[],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        assert sm._registry.get_by_id("greeting") is not None
        assert sm._registry.get_by_id("farewell") is not None
        assert sm._registry.get_by_id("chapter_1") is not None

    def test_load_dialog_registry_returns_registry(self, dialogs_file):
        reg = SessionManager.load_dialog_registry(dialogs_file)
        assert isinstance(reg, DialogRegistry)
        assert len(reg) == 3

    def test_load_dialog_registry_empty_on_missing_file(self, tmp_path):
        reg = SessionManager.load_dialog_registry(str(tmp_path / "missing.json"))
        assert isinstance(reg, DialogRegistry)
        assert len(reg) == 0

    def test_build_agenda_context_uses_completed_dialogs(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=[],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        sm.conversation_state.completed_dialogs.append("greeting")
        ctx = sm._build_agenda_context()
        assert "greeting" in ctx.completed_ids

    def test_build_agenda_context_session_completed_starts_empty(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=[],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        sm.conversation_state.completed_dialogs.append("greeting")
        ctx = sm._build_agenda_context()
        # session_completed_ids is always fresh at context build time
        assert ctx.session_completed_ids == set()


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

    def test_empty_agenda_runs_nothing(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=[],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        sm.run()
        mock_agent.say.assert_not_called()

    def test_unknown_agenda_ids_silently_skipped(self, dialogs_file, mock_agent):
        sm = SessionManager(
            session_agenda=["nonexistent_dialog"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
        )
        sm.run()
        mock_agent.say.assert_not_called()
        assert sm.conversation_state.completed_dialogs == []


# ── session_plan_path ─────────────────────────────────────────────────────────

class TestSessionPlanPath:
    def _write_plan(self, tmp_path, sessions):
        data = {"plan_id": "test_plan", "sessions": sessions}
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def test_plan_overrides_session_agenda(self, dialogs_file, mock_agent, tmp_path):
        plan_path = self._write_plan(tmp_path, [
            {"session_index": 1, "agenda": ["greeting", "farewell"]},
        ])
        sm = SessionManager(
            session_agenda=[],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
            session_plan_path=plan_path,
        )
        assert len(sm.session_agenda) == 2
        assert sm.session_agenda[0] == "greeting"

    def test_plan_fallback_when_session_number_exceeds_templates(self, dialogs_file, mock_agent, tmp_path):
        """When session_number > all template indices, the last template is used."""
        plan_path = self._write_plan(tmp_path, [
            {"session_index": 1, "agenda": ["greeting"]},
            {"session_index": 2, "agenda": ["farewell"]},
        ])
        # No participant history → session_number=1 → uses template 1
        sm = SessionManager(
            session_agenda=[],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
            session_plan_path=plan_path,
        )
        assert sm.session_agenda == ["greeting"]

    def test_missing_plan_falls_back_to_supplied_agenda(self, dialogs_file, mock_agent, tmp_path):
        missing_path = str(tmp_path / "nonexistent_plan.json")
        sm = SessionManager(
            session_agenda=["greeting"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
            session_plan_path=missing_path,
        )
        # Plan load fails → session_agenda unchanged
        assert sm.session_agenda == ["greeting"]


# ── session_index ─────────────────────────────────────────────────────────────

class TestSessionIndex:
    def test_session_index_selects_correct_template(self, dialogs_file, mock_agent, tmp_path):
        data = {
            "plan_id": "test_plan",
            "sessions": [
                {"session_index": 1, "agenda": ["greeting"]},
                {"session_index": 2, "agenda": ["farewell"]},
            ],
        }
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(data), encoding="utf-8")

        # Force session index 2 despite no prior history (which would compute session 1)
        sm = SessionManager(
            session_agenda=[],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
            session_plan_path=str(plan_path),
            session_index=2,
        )
        assert sm.session_agenda == ["farewell"]


# ── reset_history_from_session ────────────────────────────────────────────────

class TestResetHistoryFromSession:
    def test_truncate_from_session_is_called(self, dialogs_file, mock_agent):
        with patch.object(ConversationState, "truncate_from_session") as mock_truncate:
            SessionManager(
                session_agenda=[],
                agent=mock_agent,
                dialog_json_path=dialogs_file,
                participant_id="alice",
                reset_history_from_session=3,
            )
        mock_truncate.assert_called_once_with(3)

    def test_reset_happens_before_plan_loading(self, dialogs_file, mock_agent, tmp_path):
        """History must be reset before the session count is read for plan resolution."""
        call_order = []

        data = {
            "plan_id": "p",
            "sessions": [{"session_index": 1, "agenda": ["greeting"]}],
        }
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(data), encoding="utf-8")

        _orig_truncate = ConversationState.truncate_from_session
        _orig_count = ConversationState.count_completed_sessions

        def _rec_truncate(self_inner, n):
            call_order.append("truncate")
            return _orig_truncate(self_inner, n)

        def _rec_count(self_inner):
            call_order.append("count")
            return _orig_count(self_inner)

        with patch.object(ConversationState, "truncate_from_session", _rec_truncate):
            with patch.object(ConversationState, "count_completed_sessions", _rec_count):
                SessionManager(
                    session_agenda=[],
                    agent=mock_agent,
                    dialog_json_path=dialogs_file,
                    participant_id="alice",
                    reset_history_from_session=1,
                    session_plan_path=str(plan_path),
                )

        assert "truncate" in call_order
        assert "count" in call_order
        assert call_order.index("truncate") < call_order.index("count")


# ── resume ────────────────────────────────────────────────────────────────────

class TestResume:
    def test_resume_reuses_incomplete_session_id(self, dialogs_file, mock_agent):
        # Create an incomplete session in the participant transcript
        state = ConversationState(participant_id="alice")
        sid = state.start_session(participant_id="alice")
        state.add_dialog_id(sid, "greeting")
        state.save()  # writes session with ended_at=None

        sm = SessionManager(
            session_agenda=["farewell"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
            participant_id="alice",
            resume=True,
        )
        assert sm.session_id == sid

    def test_resume_pre_populates_completed_ids(self, dialogs_file, mock_agent):
        state = ConversationState(participant_id="alice")
        sid = state.start_session(participant_id="alice")
        state.add_dialog_id(sid, "greeting")
        state.save()

        sm = SessionManager(
            session_agenda=["farewell"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
            participant_id="alice",
            resume=True,
        )
        assert "greeting" in sm._resume_completed_ids

    def test_resume_starts_fresh_when_no_incomplete_session(self, dialogs_file, mock_agent):
        # No participant file at all → fresh start
        sm = SessionManager(
            session_agenda=[],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
            participant_id="alice",
            resume=True,
        )
        # A fresh session is created; no pre-populated resume IDs
        assert sm._resume_completed_ids == set()
        assert sm.session_id is not None

    def test_resume_skips_already_completed_dialog(self, dialogs_file, mock_agent):
        """NarrativeDialog run in the incomplete session must not run again on resume.

        FunctionalDialogs deliberately have no ExcludeIfSeenRule (they re-run
        every session), so this test uses the narrative dialog 'chapter_1'.
        """
        state = ConversationState(participant_id="alice")
        sid = state.start_session(participant_id="alice")
        state.add_dialog_id(sid, "chapter_1")
        state.save()

        sm = SessionManager(
            session_agenda=["chapter_1"],
            agent=mock_agent,
            dialog_json_path=dialogs_file,
            participant_id="alice",
            resume=True,
        )
        sm.run()
        # chapter_1 is in _resume_completed_ids → ExcludeIfSeenRule blocks it
        mock_agent.say.assert_not_called()
