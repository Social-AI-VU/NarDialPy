"""Tests for UserModel — in-memory mapping behaviour and continuity helpers.

Redis connections are blocked by the autouse fixture in conftest.py, so all
tests run in pure in-memory mode without any external dependencies.
"""
import pytest

from nardial.user_model import UserModel


@pytest.fixture
def model():
    """A fresh UserModel in in-memory mode (no Redis)."""
    return UserModel()


# ── Basic mapping operations ──────────────────────────────────────────────────

class TestInMemoryMapping:
    def test_set_and_get(self, model):
        model["name"] = "Alice"
        assert model["name"] == "Alice"

    def test_get_missing_key_raises_key_error(self, model):
        with pytest.raises(KeyError):
            _ = model["missing"]

    def test_get_with_default_returns_default(self, model):
        assert model.get("missing", "fallback") == "fallback"

    def test_get_with_no_default_returns_none(self, model):
        assert model.get("missing") is None

    def test_contains_existing_key(self, model):
        model["x"] = 1
        assert "x" in model

    def test_contains_missing_key(self, model):
        assert "y" not in model

    def test_delete_existing_key(self, model):
        model["x"] = 1
        del model["x"]
        assert "x" not in model

    def test_delete_missing_key_does_not_raise(self, model):
        # MutableMapping.pop with default should not raise
        model.pop("nonexistent", None)

    def test_len_reflects_number_of_keys(self, model):
        model["a"] = 1
        model["b"] = 2
        assert len(model) == 2

    def test_len_empty_model_is_zero(self, model):
        assert len(model) == 0

    def test_iter_yields_all_keys(self, model):
        model["a"] = 1
        model["b"] = 2
        assert set(model) == {"a", "b"}

    def test_keys_includes_all_set_keys(self, model):
        model["k1"] = "v1"
        model["k2"] = "v2"
        assert set(model.keys()) == {"k1", "k2"}

    def test_values_includes_all_set_values(self, model):
        model["a"] = 42
        assert 42 in model.values()

    def test_items_yields_key_value_pairs(self, model):
        model["a"] = 1
        assert ("a", 1) in model.items()

    def test_update_batch_sets_multiple_keys(self, model):
        model.update({"x": 10, "y": 20})
        assert model["x"] == 10
        assert model["y"] == 20

    def test_update_with_kwargs(self, model):
        model.update(key="value")
        assert model["key"] == "value"

    def test_overwrite_existing_key(self, model):
        model["k"] = "first"
        model["k"] = "second"
        assert model["k"] == "second"

    def test_as_dict_returns_plain_dict(self, model):
        model["a"] = 1
        result = model.as_dict()
        assert isinstance(result, dict)
        assert result == {"a": 1}

    def test_dict_conversion(self, model):
        model["x"] = 99
        assert dict(model) == {"x": 99}


# ── Encoding and decoding of complex values ───────────────────────────────────

class TestEncodeDecode:
    """_encode_value / _decode_value are used for the Redis write path.
    They must round-trip any Python value that might be stored.
    """

    def test_string_round_trip(self):
        assert UserModel._decode_value(UserModel._encode_value("hello")) == "hello"

    def test_int_round_trip(self):
        assert UserModel._decode_value(UserModel._encode_value(42)) == 42

    def test_float_round_trip(self):
        assert UserModel._decode_value(UserModel._encode_value(3.14)) == 3.14

    def test_none_passes_through_unchanged(self):
        assert UserModel._encode_value(None) is None
        assert UserModel._decode_value(None) is None

    def test_bool_encoded_as_explicit_string(self):
        # bool is a subclass of int; encoding explicitly avoids ambiguity
        assert UserModel._encode_value(True) == "true"
        assert UserModel._encode_value(False) == "false"

    def test_list_encoded_as_json_tag(self):
        val = ["a", "b", "c"]
        encoded = UserModel._encode_value(val)
        assert isinstance(encoded, str)
        assert encoded.startswith("__json__:")
        assert UserModel._decode_value(encoded) == val

    def test_dict_encoded_as_json_tag(self):
        val = {"nested": True, "count": 3}
        encoded = UserModel._encode_value(val)
        assert UserModel._decode_value(encoded) == val

    def test_non_tagged_string_decoded_as_is(self):
        assert UserModel._decode_value("plain string") == "plain string"


# ── Continuity helpers ────────────────────────────────────────────────────────

class TestContinuityHelpers:
    """save_continuity / get_completed_dialogs / get_topics_of_interest
    provide a structured interface on top of the raw key-value store.
    """

    def test_empty_model_has_no_completed_dialogs(self, model):
        assert model.get_completed_dialogs() == []

    def test_empty_model_has_no_topics(self, model):
        assert model.get_topics_of_interest() == []

    def test_save_and_retrieve_completed_dialogs(self, model):
        model.save_continuity(completed_dialogs=["d1", "d2"], topics_of_interest=[])
        assert model.get_completed_dialogs() == ["d1", "d2"]

    def test_save_and_retrieve_topics(self, model):
        model.save_continuity(completed_dialogs=[], topics_of_interest=["cats", "dogs"])
        assert model.get_topics_of_interest() == ["cats", "dogs"]

    def test_save_continuity_overwrites_previous_values(self, model):
        model.save_continuity(completed_dialogs=["d1"], topics_of_interest=["cats"])
        model.save_continuity(completed_dialogs=["d1", "d2"], topics_of_interest=["dogs"])
        assert model.get_completed_dialogs() == ["d1", "d2"]
        assert model.get_topics_of_interest() == ["dogs"]

    def test_set_completed_dialogs_directly(self, model):
        model.set_completed_dialogs(["x", "y"])
        assert model.get_completed_dialogs() == ["x", "y"]

    def test_set_topics_directly(self, model):
        model.set_topics_of_interest(["music"])
        assert model.get_topics_of_interest() == ["music"]
