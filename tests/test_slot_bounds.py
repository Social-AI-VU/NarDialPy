from nardial.agenda.slot_bounds import SlotBounds


def test_default_bounds_mean_exactly_once():
    bounds = SlotBounds()

    assert bounds.count_min == 1
    assert bounds.count_max == 1
    assert bounds.duration_min is None
    assert bounds.duration_max is None


def test_json_round_trip():
    bounds = SlotBounds(count_min=2, count_max=5, duration_min=10.0, duration_max=60.0)

    data = bounds.to_dict()
    restored = SlotBounds.from_dict(data)

    assert restored.to_dict() == data


def test_from_dict_defaults_when_fields_missing():
    bounds = SlotBounds.from_dict({})

    assert bounds.count_min == 1
    assert bounds.count_max == 1
    assert bounds.duration_min is None
    assert bounds.duration_max is None

    assert SlotBounds.from_dict(None).to_dict() == bounds.to_dict()


def test_validate_catches_inverted_count_bounds():
    bounds = SlotBounds(count_min=5, count_max=1)

    errs = bounds.validate()

    assert "count_min must be <= count_max" in errs


def test_validate_catches_inverted_duration_bounds():
    bounds = SlotBounds(duration_min=60.0, duration_max=10.0)

    errs = bounds.validate()

    assert "duration_min must be <= duration_max" in errs


def test_validate_catches_negative_values():
    bounds = SlotBounds(count_min=-1, count_max=-1, duration_min=-1.0, duration_max=-1.0)

    errs = bounds.validate()

    assert len(errs) == 4


def test_validate_passes_for_default_bounds():
    assert SlotBounds().validate() == []
