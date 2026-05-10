"""Configuration for integration tests.

Integration tests require live infrastructure (Redis, SIC services, etc.).
They are skipped by default and opt-in via::

    pytest --integration

To run only integration tests::

    pytest tests/integration --integration

Infrastructure requirements per file:
- test_user_model_redis.py   : Redis server on 127.0.0.1:6379
- test_session_persistence.py: file system only (no external services)
- test_full_session.py       : file system only (no external services)
"""
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests that require live infrastructure.",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--integration"):
        return
    skip = pytest.mark.skip(reason="integration tests are opt-in; pass --integration to run")
    for item in items:
        # Mark every test whose path contains the integration directory
        if "integration" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def redirect_cwd(tmp_path, monkeypatch):
    """Route all file I/O to an isolated temp directory for every integration test."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def allow_redis(monkeypatch):
    """Re-enable the SIC Redis datastore for tests that need a live Redis connection.

    The global conftest sets _HAS_REDIS_DS=False to keep the unit test suite
    infrastructure-free. This fixture reverses that for integration tests.
    It skips the test automatically if the SIC Redis client cannot be imported.
    """
    try:
        import nardial.user_model as um
        monkeypatch.setattr(um, "_HAS_REDIS_DS", True)
    except Exception as exc:
        pytest.skip(f"SIC Redis client not available: {exc}")
