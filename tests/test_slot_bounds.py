"""Tests for SlotBounds — the count/duration constraint model for multi-resolve slots."""

import pytest
from pydantic import ValidationError

from nardial.agenda import SlotBounds
from nardial.agenda.slot_bounds import SlotBounds as SlotBoundsDirect


# ── Import paths ──────────────────────────────────────────────────────────────

class TestImportPaths:
    def test_importable_from_agenda_package(self):
        assert SlotBounds is not None

    def test_importable_from_slot_bounds_module(self):
        assert SlotBoundsDirect is SlotBounds


# ── Defaults ─────────────────────────────────────────────────────────────────

class TestSlotBoundsDefaults:
    def test_default_count_min_is_one(self):
        assert SlotBounds().count_min == 1

    def test_default_count_max_is_one(self):
        # count_min=1, count_max=1 means exactly once.
        assert SlotBounds().count_max == 1

    def test_default_duration_min_is_none(self):
        assert SlotBounds().duration_min is None

    def test_default_duration_max_is_none(self):
        assert SlotBounds().duration_max is None

    def test_default_is_exactly_once(self):
        # The combination of defaults encodes "run exactly one time".
        b = SlotBounds()
        assert b.count_min == 1 and b.count_max == 1
        assert b.duration_min is None and b.duration_max is None


# ── Field independence ────────────────────────────────────────────────────────

class TestSlotBoundsFields:
    def test_count_range(self):
        b = SlotBounds(count_min=2, count_max=4)
        assert b.count_min == 2
        assert b.count_max == 4

    def test_count_max_none_means_no_upper_limit(self):
        b = SlotBounds(count_max=None)
        assert b.count_max is None

    def test_count_min_only(self):
        b = SlotBounds(count_min=3, count_max=None)
        assert b.count_min == 3
        assert b.count_max is None

    def test_duration_max_only(self):
        b = SlotBounds(count_max=None, duration_max=180.0)
        assert b.duration_max == 180.0
        assert b.count_max is None

    def test_duration_min_only(self):
        b = SlotBounds(duration_min=120.0)
        assert b.duration_min == 120.0

    def test_all_four_fields(self):
        b = SlotBounds(count_min=1, count_max=5, duration_min=60.0, duration_max=300.0)
        assert b.count_min == 1
        assert b.count_max == 5
        assert b.duration_min == 60.0
        assert b.duration_max == 300.0


# ── JSON serialisation ────────────────────────────────────────────────────────

class TestSlotBoundsSerialisation:
    def test_default_roundtrip(self):
        original = SlotBounds()
        restored = SlotBounds.model_validate(original.model_dump())
        assert restored == original

    def test_count_range_roundtrip(self):
        original = SlotBounds(count_min=2, count_max=4)
        restored = SlotBounds.model_validate(original.model_dump())
        assert restored == original

    def test_count_max_none_serialises_as_null(self):
        b = SlotBounds(count_max=None)
        data = b.model_dump()
        assert data["count_max"] is None

    def test_count_max_none_deserialises_from_null(self):
        b = SlotBounds.model_validate({"count_max": None})
        assert b.count_max is None

    def test_duration_fields_roundtrip(self):
        original = SlotBounds(count_min=1, count_max=None, duration_min=120.0, duration_max=300.0)
        restored = SlotBounds.model_validate(original.model_dump())
        assert restored == original

    def test_empty_dict_produces_defaults(self):
        b = SlotBounds.model_validate({})
        assert b == SlotBounds()

    def test_partial_dict_uses_remaining_defaults(self):
        b = SlotBounds.model_validate({"count_min": 2})
        assert b.count_min == 2
        assert b.count_max == 1   # default unchanged
        assert b.duration_max is None


# ── Type validation ───────────────────────────────────────────────────────────

class TestSlotBoundsValidation:
    def test_count_min_must_be_int(self):
        with pytest.raises(ValidationError):
            SlotBounds(count_min="two")  # type: ignore[arg-type]

    def test_count_max_accepts_int_or_none(self):
        SlotBounds(count_max=3)
        SlotBounds(count_max=None)

    def test_duration_accepts_float_or_none(self):
        SlotBounds(duration_min=1.5, duration_max=60.0)
        SlotBounds(duration_min=None, duration_max=None)

    def test_duration_accepts_int_coerced_to_float(self):
        # Pydantic coerces int → float for float fields.
        b = SlotBounds(duration_max=180)
        assert b.duration_max == 180.0
