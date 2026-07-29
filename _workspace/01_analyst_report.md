# 01 Analyst Report — Telegram Notification Plugin

## 1. 영향받는 파일과 변경 범위

| 파일 | 종류 | 변경 범위 |
|------|------|-----------|
| `cpp_analyzer/plugins/__init__.py` | **신규 (필수)** | 빈 파일. 없으면 `setup.py`의 `find_packages()`가 `plugins` 패키지를 수집하지 못해 설치본에서 import 실패 |
| `cpp_analyzer/plugins/telegram.py` | **신규** | `TelegramNotifier` 클래스 + `format_report()`. 프로젝트 내부 모듈을 import하지 않는 leaf 모듈로 유지 (순환 import 방지) |
| `cpp_analyzer/cli/commands.py` | 수정 | 파일 끝(현재 856줄, `_render_dep_tree_node` 아래)에 `# ── notify ──` 섹션 추가. `@cli.group() def notify()` + `@notify.command("telegram")` |
| `cpp_analyzer/mcp_server.py` | 수정 | `dependency_stats`(1037줄) 뒤, `# ── entry point ──`(1040줄) **앞**에 `# ── notification tools ──` 섹션 + `@mcp.tool() def notify_telegram(...)` |
| `README.md` | 선택 | CLI Reference + MCP Tools 목록에 추가 |
| `CLAUDE.md` | 선택 | 변경 이력 표에 1행 추가 |

**변경 불필요 (확인 완료)**
- `pyproject.toml` — stdlib만 사용하므로 `dependencies` 무변경
- `setup.py` — `find_packages()`가 `__init__.py` 존재 시 자동 수집
- `requirements.txt` — 무변경
- `cpp_analyzer/__init__.py` — 2줄짜리 docstring+`__version__`만 존재. re-export 관례 없음 → **무변경**
- DB 스키마 — **변경 불필요**. 기존 `Repository.stats()` / `get_project()`로 필요한 데이터 전부 조달 가능

## 2. 기존 코드 패턴

### 2.1 CLI group + subcommand 패턴 (`commands.py`)

기존 그룹은 `query`(173줄), `trace`(277줄) 두 개. 형태가 동일합니다.

```python
@cli.group()
def query():
    """Query indexed symbols and config keys."""      # 한 줄 docstring이 --help 설명

@query.command("symbol")                              # 문자열로 서브커맨드명 명시
@click.argument("name")
@click.option("--db",         default=DEFAULT_DB, show_default=True)
@click.option("--project-id", default=None, type=int)
def query_symbol(name, db, project_id, ...):
    """Search for symbols by name."""
```

`notify`는 새 최상위 그룹이므로 `@cli.group() def notify():` + `@notify.command("telegram")` 형태.
함수명 관례: `notify_telegram` (기존: `query_symbol`, `query_config`, `trace_config` 등).

**옵션 표기 관례**: `--db`는 항상 `default=DEFAULT_DB, show_default=True`, `--project-id`는 `default=None, type=int`. 공백 패딩 정렬 스타일 사용.

**공용 헬퍼** (반드시 재사용)
- `_get_repo(db)` (58줄) — `Repository(db)` 생성 + `connect()`
- `_resolve_project(repo, project_id)` (64줄) — project_id가 None이면 유일 프로젝트 자동 선택. 0개면 `sys.exit(1)`, 2개 이상이면 목록 출력 후 `sys.exit(1)`

**에러/출력 관례**
- 성공: `console.print("[green]...[/green]")` 또는 `[bold green]`
- 경고: `console.print("[yellow]...[/yellow]")`
- 오류: `console.print("[red]...[/red]")` + `sys.exit(1)`
- **모든 return 경로에서 `repo.close()` 호출** — 조기 return 시에도 반드시

**모듈 import 관례**: 선택적 모듈은 **함수 내부 지연 import** 권장. Telegram도 함수 내부에서 지연 import.
`commands.py`에는 `import os`가 **없으므로 추가 필요**.

### 2.2 MCP tool 패턴 (`mcp_server.py`)

```python
@mcp.tool()
def get_stats(db_path: str | None = None, project_id: int | None = None) -> str:
    """
    Return statistics for the indexed project (file count, symbol count, etc.).
    """
    db   = _default_db(db_path)
    repo = _repo(db)
    pid  = _resolve_project_id(repo, project_id)
    if pid is None:
        repo.close()
        return "No project found. Run index_project first."
    ...
    repo.close()
    return "\n".join(lines)
```

- docstring이 곧 MCP 도구 설명. 인자가 있으면 `Args:` 섹션을 붙임
- 반환은 **항상 plain `str`** (Rich 마크업 금지), 여러 줄은 `"\n".join(lines)`
- 실패 시 문자열 반환. 입력 검증 실패는 `"ERROR: ..."` 접두사 형태
- 헬퍼: `_default_db()`(48줄), `_repo()`(79줄), `_resolve_project_id()`(85줄 — CLI와 달리 **exit하지 않고 `None` 반환**)
- `mcp_server.py`는 `json`, `os`, `Path` 모두 이미 import됨 → **추가 import 없음**

### 2.3 환경변수 fallback 선례

```python
def _default_db(db_path: str | None) -> str:
    return db_path or os.environ.get("CPP_ANALYZER_DB", "cpp_analysis.db")
```
→ `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`도 동일하게 `인자 or os.environ.get(...)` 우선순위(플래그 > 환경변수)로 구현.

### 2.4 통계 데이터 소스

`Repository.stats(project_id)` → dict: `files`, `symbols`, `functions`, `classes`, `calls`, `config_keys`, `config_sources`, `config_usages`, `dataflow_paths`
→ "file count / symbol count / call edges" = `s["files"]`, `s["symbols"]`, `s["calls"]`

`Repository.get_project(pid)` → `sqlite3.Row | None` — `p["name"]`, `p["root_path"]`, `p["last_indexed"]`
**dict가 아니므로 `.get()` 사용 불가**.

### 2.5 하위 패키지 관례

`cpp_analyzer/{analysis,core,db,cli}/__init__.py`는 모두 **0바이트 빈 파일**. `plugins/__init__.py`도 빈 파일로 두는 것이 일관적.

## 3. 의존 관계

```
cpp_analyzer/plugins/telegram.py     (leaf — stdlib만: urllib.request, urllib.error, json)
        ▲                    ▲
        │                    │
cli/commands.py         mcp_server.py
   (지연 import)          (상단 또는 지연 import)
        │                    │
        └── db/repository.py ┘   (stats / get_project / list_projects)
```

- `telegram.py`는 `cpp_analyzer` 내부 모듈을 **일절 import하지 않음** → 순환 없음, 단위 테스트 용이
- `commands.py` 상단에 `import os` 추가 필요

## 4. 권장 구현 순서

1. `cpp_analyzer/plugins/__init__.py` 생성 (빈 파일)
2. `cpp_analyzer/plugins/telegram.py` 작성
3. CLI — `commands.py` 말미에 `notify` 그룹 + `telegram` 서브커맨드. `import os` 추가
4. MCP — `mcp_server.py`의 `# ── entry point ──` 앞에 `notify_telegram` 도구
5. 선택: README, CLAUDE.md 업데이트

## 5. 주의할 엣지 케이스

### 치명적

1. **MCP `message` 인자 우선 처리 — DB를 열지 말 것**
   `message`가 주어지면 DB가 없어도 동작해야 함. **토큰 검증 → message 분기 → (없을 때만) DB 접근** 순서.

2. **토큰 유출 방지**
   `urllib.error.HTTPError`의 `str(e)`에 URL(토큰 포함)이 들어갈 수 있음. 경고 출력 시 status code / reason만 출력하거나 토큰 마스킹.

3. **`urllib.error.HTTPError`는 `URLError`의 서브클래스**
   `HTTPError`를 먼저 잡아야 함. 최종 `except Exception`으로 감싸 `False` 반환.

4. **`timeout` 필수** — `urlopen(timeout=10)`. 없으면 네트워크 단절 시 MCP 서버 전체 블록.

5. **`Content-Type: application/json` 헤더 필수**
   JSON body를 쓸 때 헤더 없으면 Telegram이 400 반환.

### 중요

6. **`parse_mode` 사용 금지** — 프로젝트명/경로에 `_`, `*` 등이 들어가면 파싱 깨짐. plain text 권장.

7. **메시지 길이 4096자 제한** — `send()`에서 truncate 처리 권장.

8. **`chat_id`는 문자열로 유지** — 채널(`@channelname`), 그룹(음수 ID) 모두 처리. `int()` 변환 금지.

9. **CLI vs MCP 에러 처리 비대칭** — CLI는 `sys.exit(1)`, MCP는 문자열 반환. MCP에서 `sys.exit` 금지.

10. **`repo.close()` 누락 주의** — 토큰 검증을 `_get_repo()` 호출보다 먼저 두면 문제가 사라짐 (권장).

11. **`get_project(pid)`가 `None` 반환 가능** — 존재하지 않는 `--project-id` 명시 시. `p`가 None이면 에러 처리.

12. **환경변수 우선순위 미러링** — CLI/MCP 모두 `플래그/인자 > 환경변수 > 에러`.

### 참고

13. **프록시/TLS 환경** — `HTTPS_PROXY` + 커스텀 CA 번들 환경. `urllib`은 자동 인식. CA 검증 비활성화 금지.

14. **테스트** — 기존 벤치마크(`test_dataflow.py`, `test_dependency_graph.py`, `test_parse_cache.py`)에 영향 없어야 함. 실제 네트워크 테스트 추가 금지.

15. **브랜치** — `claude/install-telegram-plugin-ZlE2C` 체크아웃 확인됨.
