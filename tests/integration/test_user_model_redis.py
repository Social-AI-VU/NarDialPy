"""Integration tests for UserModel backed by a live Redis datastore.

Requires:
    Redis server running on 127.0.0.1:6379 with password "changemeplease"
    (the default configured in UserModel).

Run with::

    pytest tests/integration/test_user_model_redis.py --integration
"""
import pytest
from nardial.user_model import UserModel

PARTICIPANT = "integration_test_participant"


@pytest.fixture
def redis_model(allow_redis):
    """A UserModel connected to the live Redis datastore.

    Skips automatically if Redis is unavailable. Cleans up the test
    participant's data before and after each test.
    """
    model = UserModel(participant_id=PARTICIPANT)
    model.set_participant(PARTICIPANT)

    if model._datastore is None:
        pytest.skip("Redis datastore not reachable; is the Redis server running?")

    # Clean up any leftover state from previous runs
    model.clear_remote()
    yield model
    model.clear_remote()


class TestRedisRoundTrip:
    def test_write_and_read_string(self, redis_model):
        redis_model["name"] = "Alice"
        # Force a fresh load from Redis
        redis_model._cache.clear()
        assert redis_model["name"] == "Alice"

    def test_write_and_read_int(self, redis_model):
        redis_model["age"] = 30
        redis_model._cache.clear()
        assert redis_model["age"] == 30

    def test_write_and_read_list(self, redis_model):
        redis_model["tags"] = ["cats", "dogs"]
        redis_model._cache.clear()
        assert redis_model["tags"] == ["cats", "dogs"]

    def test_update_batch_persisted(self, redis_model):
        redis_model.update({"x": 1, "y": 2})
        redis_model._cache.clear()
        assert redis_model["x"] == 1
        assert redis_model["y"] == 2

    def test_delete_removes_key_from_redis(self, redis_model):
        redis_model["temp"] = "value"
        del redis_model["temp"]
        redis_model._cache.clear()
        assert "temp" not in redis_model

    def test_continuity_survives_cache_flush(self, redis_model):
        redis_model.save_continuity(
            completed_dialogs=["d1", "d2"],
            topics_of_interest=["music", "art"],
        )
        redis_model._cache.clear()
        assert redis_model.get_completed_dialogs() == ["d1", "d2"]
        assert redis_model.get_topics_of_interest() == ["music", "art"]


class TestNewInstanceLoadsPersistedState:
    def test_second_instance_sees_first_writes(self, allow_redis, monkeypatch):
        """A new UserModel for the same participant loads data written by a previous one."""
        import nardial.user_model as um
        monkeypatch.setattr(um, "_HAS_REDIS_DS", True)

        writer = UserModel(participant_id=PARTICIPANT)
        writer.set_participant(PARTICIPANT)
        if writer._datastore is None:
            pytest.skip("Redis not reachable")
        writer.clear_remote()
        writer["greeting"] = "hello from writer"

        reader = UserModel(participant_id=PARTICIPANT)
        reader.set_participant(PARTICIPANT)
        assert reader["greeting"] == "hello from writer"

        writer.clear_remote()
