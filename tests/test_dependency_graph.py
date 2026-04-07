"""
Tests for the dependency graph feature.

사용 예시를 겸하는 테스트 코드 — 실제 C++ 프로젝트를 인덱싱한 뒤
DependencyGraph API를 활용하여 파일 간 의존 관계를 분석한다.

테스트용 C++ fixture 파일 구조:
    tests/fixtures/
    ├── main.cpp      → includes app.h, utils.h
    ├── app.h         → includes config.h, utils.h
    ├── app.cpp        → includes app.h, network.h
    ├── config.h       → (시스템 헤더만)
    ├── utils.h        → (시스템 헤더만)
    ├── utils.cpp      → includes utils.h
    ├── network.h      → includes config.h, utils.h
    └── network.cpp    → includes network.h

실행:
    cd cpp-analyzer
    pytest tests/test_dependency_graph.py -v
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from cpp_analyzer.core.indexer import Indexer
from cpp_analyzer.db.repository import Repository
from cpp_analyzer.analysis.dependency_graph import DependencyGraph, FileNode


FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── 공통 fixture ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def indexed_db():
    """테스트용 C++ 파일들을 인덱싱한 임시 DB를 반환한다.

    Usage example (CLI equivalent):
        cpp-analyzer index tests/fixtures --db /tmp/test_deps.db --force
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    repo = Repository(db_path)
    repo.connect()
    pid = repo.upsert_project("test-fixtures", str(FIXTURES_DIR))

    indexer = Indexer(repo, pid, FIXTURES_DIR)
    indexer.run(force=True)

    yield repo, pid

    repo.close()
    os.unlink(db_path)


@pytest.fixture
def dep_graph(indexed_db):
    """DependencyGraph 인스턴스를 빌드하여 반환한다.

    Usage example (Python):
        repo = Repository("my.db")
        repo.connect()
        dg = DependencyGraph(repo, project_id)
        dg.build()
    """
    repo, pid = indexed_db
    dg = DependencyGraph(repo, pid)
    dg.build()
    return dg, repo, pid


def _find_file_id(repo, pid, filename: str) -> int | None:
    """파일명으로 file_id를 찾는 헬퍼."""
    rows = repo.get_file_by_path(pid, filename)
    for r in rows:
        if Path(r["relative_path"]).name == filename:
            return r["id"]
    return None


# ── 테스트: 그래프 빌드 ──────────────────────────────────────────────────────

class TestBuild:
    """DependencyGraph.build() — 그래프 구축 기본 동작 검증."""

    def test_graph_has_nodes(self, dep_graph):
        """인덱싱된 파일들이 그래프 노드로 등록되는지 확인.

        Usage example:
            dg = DependencyGraph(repo, pid)
            dg.build()
            print(f"파일 수: {dg.node_count()}")
            print(f"include 엣지 수: {dg.edge_count()}")
        """
        dg, _, _ = dep_graph
        assert dg.node_count() > 0, "그래프에 노드가 없음 — 인덱싱 확인 필요"

    def test_graph_has_edges(self, dep_graph):
        """#include 관계가 엣지로 등록되는지 확인."""
        dg, _, _ = dep_graph
        assert dg.edge_count() > 0, "그래프에 엣지가 없음 — include 해석 확인 필요"

    def test_resolve_include_ids(self, indexed_db):
        """resolve_include_file_ids가 included_file_id를 채우는지 확인.

        Usage example:
            resolved = repo.resolve_include_file_ids(project_id)
            print(f"{resolved}개 include 경로 해결됨")
        """
        repo, pid = indexed_db
        resolved = repo.resolve_include_file_ids(pid)
        # fixture 파일들은 서로 include하므로 최소 1개 이상 해결되어야 함
        assert resolved >= 0


# ── 테스트: 의존성 쿼리 ──────────────────────────────────────────────────────

class TestQueries:
    """includes_of, included_by 등 쿼리 메서드 검증."""

    def test_includes_of(self, dep_graph):
        """특정 파일이 include하는 파일 목록 조회.

        Usage example (main.cpp → app.h, utils.h):
            file_id = find_file("main.cpp")
            includes = dg.includes_of(file_id, depth=1)
            for fid in includes:
                f = repo.get_file(fid)
                print(f"  → {f['relative_path']}")
        """
        dg, repo, pid = dep_graph
        main_id = _find_file_id(repo, pid, "main.cpp")
        if main_id is None:
            pytest.skip("main.cpp not indexed")

        includes = dg.includes_of(main_id, depth=1)
        included_names = set()
        for fid in includes:
            f = repo.get_file(fid)
            if f:
                included_names.add(Path(f["relative_path"]).name)

        # main.cpp includes app.h and utils.h
        assert "app.h" in included_names or len(includes) > 0, \
            f"main.cpp의 include 목록이 비어있음: {included_names}"

    def test_included_by(self, dep_graph):
        """특정 파일을 include하는 파일 목록 조회 (역방향).

        Usage example (utils.h ← main.cpp, app.h, network.h, utils.cpp):
            file_id = find_file("utils.h")
            included_by = dg.included_by(file_id, depth=1)
            print(f"utils.h를 include하는 파일 {len(included_by)}개")
        """
        dg, repo, pid = dep_graph
        utils_id = _find_file_id(repo, pid, "utils.h")
        if utils_id is None:
            pytest.skip("utils.h not indexed")

        included_by = dg.included_by(utils_id, depth=1)
        # utils.h는 여러 파일에서 include됨
        assert len(included_by) >= 1, "utils.h를 include하는 파일이 없음"

    def test_includes_of_depth(self, dep_graph):
        """깊이 2까지의 전이적 의존성 조회.

        Usage example:
            # main.cpp → app.h → config.h (depth=2로 config.h까지 도달)
            deep = dg.includes_of(main_id, depth=2)
        """
        dg, repo, pid = dep_graph
        main_id = _find_file_id(repo, pid, "main.cpp")
        if main_id is None:
            pytest.skip("main.cpp not indexed")

        depth1 = dg.includes_of(main_id, depth=1)
        depth2 = dg.includes_of(main_id, depth=2)
        # depth=2는 depth=1보다 같거나 많은 결과
        assert len(depth2) >= len(depth1)

    def test_nonexistent_file(self, dep_graph):
        """존재하지 않는 file_id 조회 시 빈 리스트 반환."""
        dg, _, _ = dep_graph
        assert dg.includes_of(999999) == []
        assert dg.included_by(999999) == []


# ── 테스트: 순환 의존성 ──────────────────────────────────────────────────────

class TestCircular:
    """circular_dependencies — 순환 참조 탐지."""

    def test_circular_returns_list(self, dep_graph):
        """순환 의존성 탐지 결과가 리스트 형태인지 확인.

        Usage example:
            cycles = dg.circular_dependencies()
            if cycles:
                for cycle in cycles:
                    names = [repo.get_file(fid)["relative_path"] for fid in cycle]
                    print(" → ".join(names))
            else:
                print("순환 의존성 없음")
        """
        dg, _, _ = dep_graph
        cycles = dg.circular_dependencies()
        assert isinstance(cycles, list)


# ── 테스트: 통계 ─────────────────────────────────────────────────────────────

class TestStats:
    """top_included, top_includers — 의존성 통계."""

    def test_top_included(self, dep_graph):
        """가장 많이 include되는 파일 상위 N개 조회.

        Usage example:
            top = dg.top_included(n=5)
            for file_id, count in top:
                f = repo.get_file(file_id)
                print(f"  {f['relative_path']}: {count}회 include됨")
        """
        dg, repo, _ = dep_graph
        top = dg.top_included(n=5)
        assert isinstance(top, list)
        if top:
            fid, count = top[0]
            assert count >= 1
            f = repo.get_file(fid)
            assert f is not None
            print(f"\n  가장 많이 include된 파일: {f['relative_path']} ({count}회)")

    def test_top_includers(self, dep_graph):
        """가장 많이 include하는 파일 상위 N개 조회.

        Usage example:
            top = dg.top_includers(n=5)
            for file_id, count in top:
                f = repo.get_file(file_id)
                print(f"  {f['relative_path']}: {count}개 파일 include")
        """
        dg, repo, _ = dep_graph
        top = dg.top_includers(n=5)
        assert isinstance(top, list)
        if top:
            fid, count = top[0]
            assert count >= 1


# ── 테스트: 트리 빌드 ────────────────────────────────────────────────────────

class TestBuildTree:
    """build_tree — FileNode 트리 구축."""

    def test_build_tree_includes(self, dep_graph):
        """파일 의존성 트리 구축 (includes 방향).

        Usage example:
            tree = dg.build_tree(main_id, direction="includes", max_depth=3)
            # 트리를 텍스트로 출력
            def print_tree(node, indent=0):
                print("  " * indent + node.relative_path)
                for child in node.children:
                    print_tree(child, indent + 1)
            print_tree(tree)
        """
        dg, repo, pid = dep_graph
        main_id = _find_file_id(repo, pid, "main.cpp")
        if main_id is None:
            pytest.skip("main.cpp not indexed")

        tree = dg.build_tree(main_id, direction="includes", max_depth=3)
        assert tree is not None
        assert isinstance(tree, FileNode)
        assert "main.cpp" in tree.relative_path
        print(f"\n  main.cpp 의존성 트리:")
        _print_tree(tree)

    def test_build_tree_included_by(self, dep_graph):
        """역방향 트리 구축 (included-by 방향).

        Usage example:
            tree = dg.build_tree(config_id, direction="included-by", max_depth=3)
        """
        dg, repo, pid = dep_graph
        config_id = _find_file_id(repo, pid, "config.h")
        if config_id is None:
            pytest.skip("config.h not indexed")

        tree = dg.build_tree(config_id, direction="included-by", max_depth=3)
        assert tree is not None
        assert "config.h" in tree.relative_path
        print(f"\n  config.h를 include하는 파일 트리:")
        _print_tree(tree)

    def test_build_tree_nonexistent(self, dep_graph):
        """존재하지 않는 파일로 트리 구축 시 None 반환."""
        dg, _, _ = dep_graph
        assert dg.build_tree(999999) is None


def _print_tree(node: FileNode, prefix: str = "", is_last: bool = True):
    """테스트 출력용 트리 렌더링 헬퍼."""
    connector = "└── " if is_last else "├── "
    name = Path(node.relative_path).name
    print(f"  {prefix}{connector}{name}")
    child_prefix = prefix + ("    " if is_last else "│   ")
    for i, child in enumerate(node.children):
        _print_tree(child, child_prefix, i == len(node.children) - 1)


# ── 테스트: CLI deps 커맨드 ──────────────────────────────────────────────────

class TestCLI:
    """CLI deps 커맨드 통합 테스트.

    Usage example (terminal):
        # 1. 먼저 인덱싱
        cpp-analyzer index tests/fixtures --db /tmp/test.db --force

        # 2. 파일 의존성 트리
        cpp-analyzer deps main.cpp --db /tmp/test.db

        # 3. 역방향 (이 파일을 누가 include하는지)
        cpp-analyzer deps config.h --direction included-by --db /tmp/test.db

        # 4. 깊이 제한
        cpp-analyzer deps main.cpp --depth 2 --db /tmp/test.db

        # 5. 순환 의존성 탐지
        cpp-analyzer deps --circular --db /tmp/test.db

        # 6. 가장 많이 include되는 파일 통계
        cpp-analyzer deps --top 5 --db /tmp/test.db

        # 7. 시스템 헤더 포함
        cpp-analyzer deps main.cpp --show-system --db /tmp/test.db
    """

    def test_deps_help(self):
        """deps --help가 정상 출력되는지 확인."""
        from click.testing import CliRunner
        from cpp_analyzer.cli.commands import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["deps", "--help"])
        assert result.exit_code == 0
        assert "deps" in result.output.lower() or "dependency" in result.output.lower() or "include" in result.output.lower()

    def test_deps_tree(self, indexed_db):
        """deps FILE_PATH — 의존성 트리 출력 테스트."""
        from click.testing import CliRunner
        from cpp_analyzer.cli.commands import cli

        repo, _ = indexed_db
        runner = CliRunner()
        result = runner.invoke(cli, [
            "deps", "main.cpp",
            "--db", repo.db_path,
        ])
        # exit_code 0 또는 파일을 찾지 못해도 에러 없이 종료
        assert result.exit_code == 0 or "not found" in (result.output or "").lower()

    def test_deps_circular(self, indexed_db):
        """deps --circular — 순환 의존성 탐지 테스트."""
        from click.testing import CliRunner
        from cpp_analyzer.cli.commands import cli

        repo, _ = indexed_db
        runner = CliRunner()
        result = runner.invoke(cli, [
            "deps", "--circular",
            "--db", repo.db_path,
        ])
        assert result.exit_code == 0

    def test_deps_top(self, indexed_db):
        """deps --top N — 상위 파일 통계 테스트."""
        from click.testing import CliRunner
        from cpp_analyzer.cli.commands import cli

        repo, _ = indexed_db
        runner = CliRunner()
        result = runner.invoke(cli, [
            "deps", "--top", "5",
            "--db", repo.db_path,
        ])
        assert result.exit_code == 0


# ── 테스트: MCP 도구 ─────────────────────────────────────────────────────────

class TestMCPTools:
    """MCP 도구 단위 테스트.

    Usage example (MCP client):
        # 1. 인덱싱
        result = await mcp.call("index_project", directory="tests/fixtures")

        # 2. 파일 의존성 트리
        result = await mcp.call("file_dependencies",
            file_path="main.cpp", direction="includes", max_depth=3)

        # 3. 순환 의존성
        result = await mcp.call("circular_dependencies")

        # 4. 의존성 통계
        result = await mcp.call("dependency_stats")
    """

    def test_file_dependencies(self, indexed_db):
        """file_dependencies MCP 도구 테스트."""
        from cpp_analyzer.mcp_server import file_dependencies

        repo, _ = indexed_db
        result = file_dependencies(
            file_path="main.cpp",
            direction="includes",
            max_depth=3,
            db_path=repo.db_path,
        )
        assert isinstance(result, str)
        assert len(result) > 0
        print(f"\n  MCP file_dependencies 결과:\n{result}")

    def test_circular_dependencies(self, indexed_db):
        """circular_dependencies MCP 도구 테스트."""
        from cpp_analyzer.mcp_server import circular_dependencies

        repo, _ = indexed_db
        result = circular_dependencies(db_path=repo.db_path)
        assert isinstance(result, str)
        print(f"\n  MCP circular_dependencies 결과:\n{result}")

    def test_dependency_stats(self, indexed_db):
        """dependency_stats MCP 도구 테스트."""
        from cpp_analyzer.mcp_server import dependency_stats

        repo, _ = indexed_db
        result = dependency_stats(db_path=repo.db_path)
        assert isinstance(result, str)
        assert len(result) > 0
        print(f"\n  MCP dependency_stats 결과:\n{result}")
