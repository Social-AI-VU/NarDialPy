import json

from nardial.agenda.session_plan import SessionPlan, SessionTemplate, load_session_plan


def make_plan():
    return SessionPlan(
        plan_id="onboarding",
        sessions=[
            SessionTemplate(session_index=1, agenda=["greeting_1", "intro_1"]),
            SessionTemplate(session_index=2, agenda=["greeting_1", "chapter_2"]),
            SessionTemplate(session_index=3, agenda=["greeting_1", "chapter_3", "farewell_1"]),
        ],
    )


def test_get_template_exact_match():
    plan = make_plan()

    template = plan.get_template(2)

    assert template.session_index == 2
    assert template.agenda == ["greeting_1", "chapter_2"]


def test_get_template_falls_back_to_highest_indexed_steady_state_template():
    plan = make_plan()

    template = plan.get_template(10)

    assert template.session_index == 3
    assert template.agenda == ["greeting_1", "chapter_3", "farewell_1"]


def test_get_template_returns_none_when_no_templates():
    plan = SessionPlan(plan_id="empty", sessions=[])

    assert plan.get_template(1) is None


def test_json_round_trip():
    plan = make_plan()

    data = plan.to_dict()
    restored = SessionPlan.from_dict(data)

    assert restored.to_dict() == data


def test_validate_passes_for_well_formed_plan():
    assert make_plan().validate() == []


def test_validate_catches_missing_plan_id():
    plan = SessionPlan(plan_id="", sessions=[SessionTemplate(session_index=1, agenda=[])])

    assert "plan_id must be a non-empty string" in plan.validate()


def test_validate_catches_empty_sessions():
    plan = SessionPlan(plan_id="empty", sessions=[])

    assert "sessions must be a non-empty list" in plan.validate()


def test_validate_catches_duplicate_session_index():
    plan = SessionPlan(
        plan_id="dup",
        sessions=[
            SessionTemplate(session_index=1, agenda=[]),
            SessionTemplate(session_index=1, agenda=[]),
        ],
    )

    errs = plan.validate()

    assert any("duplicate session_index" in e for e in errs)


def test_validate_catches_invalid_session_index():
    plan = SessionPlan(plan_id="bad", sessions=[SessionTemplate(session_index=0, agenda=[])])

    errs = plan.validate()

    assert any("session_index must be >= 1" in e for e in errs)


def test_load_session_plan_round_trips_through_disk(tmp_path):
    plan = make_plan()
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")

    loaded, errors = load_session_plan(str(path))

    assert errors == []
    assert loaded.to_dict() == plan.to_dict()


def test_load_session_plan_missing_file_returns_error_not_raise(tmp_path):
    plan, errors = load_session_plan(str(tmp_path / "does_not_exist.json"))

    assert plan is None
    assert len(errors) == 1


def test_load_session_plan_surfaces_validation_errors(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"plan_id": "", "sessions": []}), encoding="utf-8")

    plan, errors = load_session_plan(str(path))

    assert plan is not None
    assert len(errors) == 2
