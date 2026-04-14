"""Benchmark parse_cache cold/warm speedup.

Usage:
    .venv/bin/python scripts/bench_parse_cache.py <source_dir> [--db <path>]

Measures:
    cold (cache cleared) → trace() time + cache_misses
    warm (cache hot)     → trace() time + cache_hits
    bypass (use_cache=False) → trace() time
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from cpp_analyzer.core.indexer import Indexer
from cpp_analyzer.db.repository import Repository
from cpp_analyzer.analysis.taint_tracker import TaintTracker


def _run(repo, pid, *, use_cache):
    t = TaintTracker(repo, pid, use_cache=use_cache)
    t0 = time.perf_counter()
    paths = t.trace(max_depth=5, max_paths=200)
    dt = time.perf_counter() - t0
    return dt, len(paths), t._cache_hits, t._cache_misses


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source_dir")
    ap.add_argument("--db", default="/tmp/bench_parse_cache.db")
    args = ap.parse_args()

    src = Path(args.source_dir).resolve()
    db_path = args.db
    Path(db_path).unlink(missing_ok=True)

    repo = Repository(db_path)
    repo.connect()
    pid = repo.upsert_project(src.name, [str(src)])

    print(f"Indexing {src} ...")
    t0 = time.perf_counter()
    Indexer(repo, pid, [src]).run()
    print(f"  index: {time.perf_counter()-t0:.2f}s")

    # cold: ensure no cache rows
    repo._conn.execute("DELETE FROM parse_cache")
    repo._conn.commit()

    cold_dt, cold_n, _, cold_miss = _run(repo, pid, use_cache=True)
    warm_dt, warm_n, warm_hit, _  = _run(repo, pid, use_cache=True)
    bypass_dt, bypass_n, _, _     = _run(repo, pid, use_cache=False)

    total_files = repo._conn.execute(
        "SELECT COUNT(*) c FROM files WHERE project_id=?", (pid,)
    ).fetchone()["c"]

    print()
    print(f"files        : {total_files}")
    print(f"cold  trace  : {cold_dt:.2f}s  paths={cold_n}  misses={cold_miss}")
    print(f"warm  trace  : {warm_dt:.2f}s  paths={warm_n}  hits={warm_hit}")
    print(f"bypass trace : {bypass_dt:.2f}s  paths={bypass_n}  (use_cache=False)")
    if warm_dt > 0:
        print(f"speedup (cold/warm)  = {cold_dt/warm_dt:.1f}x")
    denom = warm_hit + (cold_miss if warm_hit == 0 else 0)
    if (warm_hit + cold_miss) > 0 and warm_hit > 0:
        hit_rate = warm_hit / (warm_hit + 0) if warm_hit else 0
        print(f"hit_rate (warm run)  = {warm_hit}/{total_files} = {warm_hit/max(total_files,1)*100:.1f}%")

    repo.close()


if __name__ == "__main__":
    main()
