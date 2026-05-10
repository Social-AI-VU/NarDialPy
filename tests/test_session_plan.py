"""Tests for SessionPlan, SessionTemplate, and load_session_plan."""
import json
import pytest

from nardial.agenda import (
    DialogRef,
    NarrativeSlot,
    SessionPlan,
    SessionTemplate,
    load_session_plan,
)


class TestSessionTemplate:
    def test_get_agenda_items_coerces_strings(self):
        template = SessionTemplate(session_index=1, agenda=["greeting", "farewell"])
        items = template.get_agenda_items()
        assert all(isinstance(i, DialogRef) for i in items)
        assert items[0].id == "greeting"

    def test_get_agenda_items_coerces_dicts(self):
        template = SessionTemplate(
            session_index=1,
            agenda=[{"type": "narrative_slot", "thread": "intro"}],
        )
        items = template.get_agenda_items()
        assert isinstance(items[0], NarrativeSlot)

    def test_get_agenda_items_empty_agenda(self):
        template = SessionTemplate(session_index=1, agenda=[])
        assert template.get_agenda_items() == []


class TestSessionPlan:
    def _plan(self):
        return SessionPlan(
            plan_id="test_plan",
            sessions=[
                SessionTemplate(session_index=1, agenda=["a"]),
                SessionTemplate(session_index=2, agenda=["b"]),
                SessionTemplate(session_index=3, agenda=["c"]),
            ],
        )

    def test_get_template_exact_match(self):
        plan = self._plan()
        t = plan.get_template(2)
        assert t is not None
        assert t.session_index == 2
        assert t.agenda == ["b"]

    def test_get_template_fallback_to_last_when_exceeded(self):
        plan = self._plan()
        t = plan.get_template(99)
        assert t is not None
        assert t.session_index == 3  # last defined template

    def test_get_template_returns_none_for_empty_plan(self):
        plan = SessionPlan(plan_id="empty", sessions=[])
        assert plan.get_template(1) is None

    def test_get_template_first_session(self):
        plan = self._plan()
        t = plan.get_template(1)
        assert t.agenda == ["a"]

    def test_plan_id_preserved(self):
        plan = SessionPlan(plan_id="my_study", sessions=[])
        assert plan.plan_id == "my_study"


class TestLoadSessionPlan:
    def test_round_trips_json(self, tmp_path):
        data = {
            "plan_id": "study_arc",
            "sessions": [
                {"session_index": 1, "agenda": ["greeting", "farewell"]},
                {"session_index": 2, "agenda": [{"type": "chitchat_slot"}]},
            ],
        }
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(data), encoding="utf-8")

        plan = load_session_plan(str(plan_file))
        assert plan.plan_id == "study_arc"
        assert len(plan.sessions) == 2
        assert plan.sessions[0].session_index == 1
        assert plan.sessions[1].agenda[0] == {"type": "chitchat_slot"}

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_session_plan(str(tmp_path / "nonexistent.json"))

    def test_invalid_json_raises(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not valid json {{{", encoding="utf-8")
        with pytest.raises(Exception):
            load_session_plan(str(bad))
