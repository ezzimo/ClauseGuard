"""Global test isolation.

Every test — unit or integration — must write contract state and audit log
lines under a per-test tmp_path, never under the real clauseguard-app/backend/storage/
directory. That real directory holds production/demo data (e.g. contract
f3ff5109...) and got polluted with hundreds of test fixtures before this
fixture existed. See scripts/cleanup_storage.py for the one-time cleanup.
"""

from pathlib import Path

import pytest

from config import settings


@pytest.fixture(scope="session", autouse=True)
def _quarantine_default_storage(tmp_path_factory):
    """Permanently move the *default* storage location for the whole test
    session before any test runs.

    Some tests intentionally leave a background analysis thread running past
    the end of the test (e.g. a 409-double-analyze test that doesn't wait for
    the slow mocked flow to finish). That thread later calls _storage_path()
    on its own schedule, by which point the per-test monkeypatch below has
    already been undone. Without this session-level fixture, that write would
    land back on the real default ("storage") instead of a harmless one.
    """
    session_dir = tmp_path_factory.mktemp("session_storage")
    settings.storage_dir = str(session_dir)
    settings.audit_log_path = str(session_dir / "audit_log.jsonl")
    yield


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    audit_log_path = storage_dir / "audit_log.jsonl"

    monkeypatch.setattr(settings, "storage_dir", str(storage_dir))
    monkeypatch.setattr(settings, "audit_log_path", str(audit_log_path))

    resolved_storage = Path(settings.storage_dir).resolve()
    resolved_tmp = tmp_path.resolve()
    assert str(resolved_storage).startswith(str(resolved_tmp)), (
        f"Test storage isolation is broken: settings.storage_dir resolved to "
        f"{resolved_storage}, which is not under this test's tmp_path "
        f"{resolved_tmp}. Refusing to run — this would pollute real storage."
    )

    yield
