"""Unit tests for parse_cache persistence layer."""

import tempfile
from pathlib import Path

from cpp_analyzer.db.repository import Repository


def _new_repo():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    repo = Repository(tmp.name)
    repo.connect()
    return repo, tmp.name


def _make_file(repo: Repository, project_id: int, rp: str, file_hash: str) -> int:
    return repo.upsert_file(
        project_id=project_id,
        path=f"/fake/{rp}",
        relative_path=rp,
        file_hash=file_hash,
        last_modified=0.0,
        line_count=1,
    )


def test_upsert_and_get_roundtrip():
    repo, _ = _new_repo()
    pid = repo.upsert_project("p", ["/fake"])
    fid = _make_file(repo, pid, "a.c", "h1")
    payload = {"assignments": [{"lhs": "x", "rhs": "1"}], "calls": []}
    repo.upsert_parse_cache(fid, "h1", payload)
    got = repo.get_parse_cache(fid, "h1")
    assert got == payload


def test_hash_mismatch_returns_none():
    repo, _ = _new_repo()
    pid = repo.upsert_project("p", ["/fake"])
    fid = _make_file(repo, pid, "a.c", "h1")
    repo.upsert_parse_cache(fid, "h1", {"x": 1})
    assert repo.get_parse_cache(fid, "h2") is None


def test_upsert_overwrites():
    repo, _ = _new_repo()
    pid = repo.upsert_project("p", ["/fake"])
    fid = _make_file(repo, pid, "a.c", "h1")
    repo.upsert_parse_cache(fid, "h1", {"v": 1})
    repo.upsert_parse_cache(fid, "h2", {"v": 2})
    assert repo.get_parse_cache(fid, "h2") == {"v": 2}
    assert repo.get_parse_cache(fid, "h1") is None


def test_cascade_on_file_delete():
    repo, _ = _new_repo()
    pid = repo.upsert_project("p", ["/fake"])
    fid = _make_file(repo, pid, "a.c", "h1")
    repo.upsert_parse_cache(fid, "h1", {"v": 1})
    # Delete file row directly, cascade should drop the cache.
    repo._conn.execute("DELETE FROM files WHERE id=?", (fid,))
    repo._conn.commit()
    row = repo._conn.execute(
        "SELECT COUNT(*) c FROM parse_cache WHERE file_id=?", (fid,)
    ).fetchone()
    assert row["c"] == 0


def test_config_scan_state_roundtrip():
    repo, _ = _new_repo()
    pid = repo.upsert_project("p", ["/fake"])
    fid = _make_file(repo, pid, "a.c", "h1")
    repo.mark_config_scanned(fid, "h1")
    state = repo.get_config_scan_state(pid)
    assert state == {fid: "h1"}
    repo.mark_config_scanned(fid, "h2")
    assert repo.get_config_scan_state(pid) == {fid: "h2"}


def test_invalidate_parse_cache():
    repo, _ = _new_repo()
    pid = repo.upsert_project("p", ["/fake"])
    fid = _make_file(repo, pid, "a.c", "h1")
    repo.upsert_parse_cache(fid, "h1", {"v": 1})
    repo.invalidate_parse_cache(fid)
    assert repo.get_parse_cache(fid, "h1") is None
