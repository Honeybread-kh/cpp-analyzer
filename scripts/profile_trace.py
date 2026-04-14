"""Profile TaintTracker.trace() to find the hot path.

Usage:
    .venv/bin/python scripts/profile_trace.py <source_dir> [--db <path>]
"""

from __future__ import annotations

import argparse
import cProfile
import pstats
from pathlib import Path

from cpp_analyzer.core.indexer import Indexer
from cpp_analyzer.db.repository import Repository
from cpp_analyzer.analysis.taint_tracker import TaintTracker


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source_dir")
    ap.add_argument("--db", default="/tmp/profile_trace.db")
    ap.add_argument("--reuse-db", action="store_true")
    args = ap.parse_args()

    src = Path(args.source_dir).resolve()
    db_path = args.db
    if not args.reuse_db:
        Path(db_path).unlink(missing_ok=True)

    repo = Repository(db_path)
    repo.connect()
    pid = repo.upsert_project(src.name, [str(src)])

    if not args.reuse_db:
        print(f"Indexing {src} ...")
        Indexer(repo, pid, [src]).run()

    # warm parse_cache first so profile focuses on trace() body
    TaintTracker(repo, pid, use_cache=True).trace(max_depth=5, max_paths=200)
    # drop trace_result_cache so measured run exercises the full trace path
    # (parse_cache stays warm; that's realistic for repeated query workloads)
    repo.clear_trace_cache(pid)

    tracker = TaintTracker(repo, pid, use_cache=True)
    prof = cProfile.Profile()
    prof.enable()
    paths = tracker.trace(max_depth=5, max_paths=200)
    prof.disable()

    print(f"paths={len(paths)} hits={tracker._cache_hits} misses={tracker._cache_misses}")
    print()

    st = pstats.Stats(prof).sort_stats("cumulative")
    print("=== Top 25 by cumulative time ===")
    st.print_stats(25)
    print()
    print("=== Top 25 by total (self) time ===")
    st.sort_stats("tottime").print_stats(25)

    repo.close()


if __name__ == "__main__":
    main()
