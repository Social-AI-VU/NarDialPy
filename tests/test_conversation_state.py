import json
import pytest

from nardial.conversation_state import ConversationState, Session


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


# ── _sanitize_participant_id ──────────────────────────────────────────────────

_sanitize = ConversationState._sanitize_participant_id


class TestSanitizeParticipantId:
    def test_none_returns_anonymous_sentinel(self):
        assert _sanitize(None) == "__unknown__"

    def test_normal_id_passes_through(self):
        assert _sanitize("alice") == "alice"

    def test_whitespace_replaced_with_underscore(self):
        assert _sanitize("alice bob") == "alice_bob"

    def test_special_chars_replaced_with_underscore(self):
        result = _sanitize("user@example.com")
        assert "@" not in result
        assert result == "user_example.com"

    def test_reserved_name_con_gets_prefix(self):
        assert _sanitize("CON") == "_CON"

    def test_reserved_name_nul_gets_prefix(self):
        assert _sanitize("NUL") == "_NUL"

    def test_reserved_name_case_insensitive(self):
        # "con" and "CON" are both reserved on Windows
        assert _sanitize("con").startswith("_")

    def test_empty_string_returns_fallback(self):
        assert _sanitize("") == "participant"

    def test_whitespace_only_returns_fallback(self):
        assert _sanitize("   ") == "participant"


# ── add_events / add_dialog_id ────────────────────────────────────────────────

class TestAddEventsAndDialogId:
    def test_add_events_appends_to_session(self, tmp_path):
        state = ConversationState(base_dir=str(tmp_path))
        sid = state.start_session()
        events = [{"type": "dialog_start", "dialog_id": "intro"}]
        state.add_events(sid, events)
        sess = state._get_session(sid)
        assert len(sess.events) == 1
        assert sess.events[0]["dialog_id"] == "intro"

    def test_add_events_multiple_calls_accumulate(self, tmp_path):
        state = ConversationState(base_dir=str(tmp_path))
        sid = state.start_session()
        state.add_events(sid, [{"type": "a"}])
        state.add_events(sid, [{"type": "b"}, {"type": "c"}])
        assert len(state._get_session(sid).events) == 3

    def test_add_dialog_id_records_id(self, tmp_path):
        state = ConversationState(base_dir=str(tmp_path))
        sid = state.start_session()
        state.add_dialog_id(sid, "greeting")
        assert "greeting" in state._get_session(sid).dialog_ids

    def test_add_dialog_id_is_deduplicated(self, tmp_path):
        state = ConversationState(base_dir=str(tmp_path))
        sid = state.start_session()
        state.add_dialog_id(sid, "greeting")
        state.add_dialog_id(sid, "greeting")
        assert state._get_session(sid).dialog_ids.count("greeting") == 1

    def test_get_session_raises_for_unknown_id(self, tmp_path):
        state = ConversationState(base_dir=str(tmp_path))
        with pytest.raises(KeyError):
            state._get_session("sess_9999")


# ── _derive_dialog_ids_from_events ────────────────────────────────────────────

class TestDeriveDialogIdsFromEvents:
    def test_extracts_ids_from_start_and_end_events(self):
        sess = Session(session_id="s1", events=[
            {"type": "dialog_start", "dialog_id": "greeting"},
            {"type": "say", "text": "Hello"},
            {"type": "dialog_end", "dialog_id": "greeting"},
        ])
        ConversationState._derive_dialog_ids_from_events(sess)
        assert "greeting" in sess.dialog_ids

    def test_deduplicates_ids_across_events(self):
        sess = Session(session_id="s1", events=[
            {"type": "dialog_start", "dialog_id": "quiz"},
            {"type": "dialog_end", "dialog_id": "quiz"},
        ])
        ConversationState._derive_dialog_ids_from_events(sess)
        assert sess.dialog_ids.count("quiz") == 1

    def test_ignores_events_without_dialog_id(self):
        sess = Session(session_id="s1", events=[
            {"type": "say", "text": "Hi"},
        ])
        ConversationState._derive_dialog_ids_from_events(sess)
        assert sess.dialog_ids == []

    def test_empty_events_leaves_dialog_ids_unchanged(self):
        sess = Session(session_id="s1", events=[])
        ConversationState._derive_dialog_ids_from_events(sess)
        assert sess.dialog_ids == []

    def test_multiple_dialogs_preserved_in_order(self):
        sess = Session(session_id="s1", events=[
            {"type": "dialog_start", "dialog_id": "intro"},
            {"type": "dialog_start", "dialog_id": "quiz"},
        ])
        ConversationState._derive_dialog_ids_from_events(sess)
        assert sess.dialog_ids == ["intro", "quiz"]


# ── _collect_topics_from_summaries ────────────────────────────────────────────

class TestCollectTopicsFromSummaries:
    def test_collects_topics_across_sessions(self):
        sessions = [
            Session(session_id="s1", summary={"topics_of_interest": ["cats", "dogs"]}),
            Session(session_id="s2", summary={"topics_of_interest": ["birds"]}),
        ]
        topics = ConversationState._collect_topics_from_summaries(sessions)
        assert set(topics) == {"cats", "dogs", "birds"}

    def test_deduplicates_case_insensitively(self):
        sessions = [
            Session(session_id="s1", summary={"topics_of_interest": ["Cats"]}),
            Session(session_id="s2", summary={"topics_of_interest": ["cats"]}),
        ]
        topics = ConversationState._collect_topics_from_summaries(sessions)
        assert len(topics) == 1

    def test_skips_non_string_entries(self):
        sessions = [
            Session(session_id="s1", summary={"topics_of_interest": ["valid", 42, None]}),
        ]
        topics = ConversationState._collect_topics_from_summaries(sessions)
        assert topics == ["valid"]

    def test_empty_sessions_returns_empty(self):
        assert ConversationState._collect_topics_from_summaries([]) == []

    def test_session_with_no_summary_is_safe(self):
        sess = Session(session_id="s1")
        topics = ConversationState._collect_topics_from_summaries([sess])
        assert topics == []


# ── _atomic_write_json ────────────────────────────────────────────────────────

class TestAtomicWriteJson:
    def test_writes_valid_json(self, tmp_path):
        path = tmp_path / "out.json"
        ConversationState._atomic_write_json(path, {"key": "value"})
        data = json.loads(path.read_text())
        assert data["key"] == "value"

    def test_temp_file_is_cleaned_up(self, tmp_path):
        path = tmp_path / "out.json"
        ConversationState._atomic_write_json(path, {})
        tmp_file = path.with_suffix(path.suffix + ".tmp")
        assert not tmp_file.exists()

    def test_creates_parent_directories(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "out.json"
        ConversationState._atomic_write_json(path, {"x": 1})
        assert path.exists()
