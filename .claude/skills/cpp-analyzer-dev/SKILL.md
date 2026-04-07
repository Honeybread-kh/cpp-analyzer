---
name: cpp-analyzer-dev
description: "cpp-analyzer 프로젝트의 코드 구현 스킬. 새 분석 기능 추가, CLI 커맨드/MCP 도구 구현, DB 스키마 확장, 버그 수정 등 모든 코드 작성 작업을 수행. developer 에이전트가 사용."
---

# cpp-analyzer Development Skill

cpp-analyzer 프로젝트의 전 계층에 걸쳐 코드를 작성하고 수정하는 스킬.

## 구현 순서 (의존 방향)

코드 변경 시 반드시 아래 순서를 따른다. 하위 계층을 먼저 구현해야 상위 계층에서 참조할 수 있다.

```
1. db/schema.py        → 테이블/컬럼 추가
2. db/repository.py    → 쿼리 메서드 추가
3. analysis/models.py  → 결과 데이터 클래스 정의
4. analysis/*.py       → 분석 로직 구현
5. cli/commands.py     → CLI 커맨드 추가
6. mcp_server.py       → MCP 도구 추가
```

## 계층별 패턴

### DB 스키마 (db/schema.py)
```python
# 테이블 정의는 SCHEMA 리스트에 CREATE TABLE IF NOT EXISTS 문 추가
SCHEMA = [
    "CREATE TABLE IF NOT EXISTS new_table (...)",
]
```

### Repository (db/repository.py)
```python
# 모든 DB 접근은 Repository 메서드로
def new_query(self, project_id: int, **kwargs) -> list[dict]:
    sql = "SELECT ... FROM ... WHERE project_id = ?"
    return [dict(row) for row in self.conn.execute(sql, (project_id,))]
```

### Analysis 모듈
```python
# 독립 클래스로 구현, Repository를 주입받음
class NewAnalyzer:
    def __init__(self, repo: Repository, project_id: int):
        self.repo = repo
        self.project_id = project_id
    
    def analyze(self) -> AnalysisResult:
        ...
```

### CLI (cli/commands.py)
```python
@cli.command()  # 또는 @existing_group.command("name")
@click.argument("arg_name")
@click.option("--db", default=DEFAULT_DB, show_default=True)
@click.option("--project-id", default=None, type=int)
def new_command(arg_name, db, project_id):
    """Short description for --help."""
    repo = _get_repo(db)
    pid = _resolve_project(repo, project_id)
    # ... Rich Table/Tree로 출력 ...
    repo.close()
```

### MCP 도구 (mcp_server.py)
```python
@mcp.tool()
def new_tool(
    param: str,
    db_path: str | None = None,
    project_id: int | None = None,
) -> str:
    """Docstring이 MCP 도구 설명이 된다."""
    db = _default_db(db_path)
    repo = _repo(db)
    pid = _resolve_project_id(repo, project_id)
    if pid is None:
        repo.close()
        return "No project found."
    # ... 문자열로 결과 반환 ...
    repo.close()
    return "\n".join(lines)
```

## CLI ↔ MCP 미러링 규칙

- CLI에 추가한 커맨드는 반드시 MCP에도 대응 도구를 추가한다
- 파라미터 이름은 가능한 동일하게 (CLI: `--max-depth`, MCP: `max_depth`)
- CLI는 Rich로 포맷팅, MCP는 plain text 문자열 반환
- 비즈니스 로직은 analysis/ 계층에 두고, CLI/MCP는 호출만 한다

## 기존 의존성

변경 전 확인할 핵심 의존성:
- `libclang` — AST 파싱 (core/ast_parser.py)
- `tree-sitter` — 폴백 파서 (analysis/ts_parser.py)
- `networkx` — 그래프 자료구조 (analysis/call_graph.py)
- `click` — CLI 프레임워크
- `rich` — CLI 출력 포맷팅
- `mcp` (FastMCP) — MCP 서버
- `PyYAML` — config_patterns.yaml 파싱
