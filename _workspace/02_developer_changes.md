# 02 Developer Changes — Telegram Notification Plugin

브랜치: `claude/install-telegram-plugin-ZlE2C`

## 변경 파일 목록

| 파일 | 종류 | 내용 |
|------|------|------|
| `cpp_analyzer/plugins/__init__.py` | 신규 | 0바이트 빈 파일. `find_packages()`가 `plugins` 서브패키지를 수집하도록 함 (기존 `analysis/`, `core/`, `db/`, `cli/` 관례와 동일) |
| `cpp_analyzer/plugins/telegram.py` | 신규 | `TelegramNotifier` 클래스 + `format_report()` 함수 |
| `cpp_analyzer/cli/commands.py` | 수정 | 파일 말미(`_render_dep_tree_node` 뒤)에 `# ── notify ──` 섹션 추가 — `notify` 그룹 + `telegram` 서브커맨드 |
| `cpp_analyzer/mcp_server.py` | 수정 | `# ── entry point ──` 바로 앞에 `# ── notification tools ──` 섹션 추가 — `notify_telegram` MCP 도구 |

**변경 없음:** `pyproject.toml`, `setup.py`, `requirements.txt`, DB 스키마, `cpp_analyzer/__init__.py`
→ stdlib만 사용하므로 신규 의존성 0건. `Repository.stats()` / `get_project()`로 데이터 전부 조달.

## 신규 심볼

| 심볼 | 위치 | 시그니처 |
|------|------|----------|
| `TelegramNotifier` | `plugins/telegram.py` | `__init__(self, token: str, chat_id: str)` |
| `TelegramNotifier.send` | `plugins/telegram.py` | `send(self, text: str) -> bool` |
| `format_report` | `plugins/telegram.py` | `format_report(project_name: str, stats: dict) -> str` |
| `notify` (CLI group) | `cli/commands.py` | `cpp-analyzer notify` |
| `notify_telegram` (CLI cmd) | `cli/commands.py` | `--db / --project-id / --token / --chat-id` |
| `notify_telegram` (MCP tool) | `mcp_server.py` | `token, chat_id, db_path, project_id, message` |

모듈 상수: `API_BASE`, `MAX_MESSAGE_LEN=4096`, `TIMEOUT=10`

## 주요 결정 사항

1. **leaf 모듈 유지** — `plugins/telegram.py`는 `json`, `urllib.request`, `urllib.error`만 import.
   `cpp_analyzer` 내부 모듈을 일절 참조하지 않아 순환 import 불가, 단위 테스트 시 DB 불필요.

2. **토큰 유출 방지** — 토큰은 request URL(`/bot{token}/sendMessage`)에 들어가므로
   `HTTPError`의 `str(e)`에 그대로 노출된다. 따라서 예외 메시지를 절대 그대로 출력하지 않고
   `e.code` / `e.reason` / `type(e).__name__`만 출력한다. 세 경로(HTTPError, URLError, Exception)
   모두 토큰 미노출을 실측 검증했다.

3. **예외 처리 순서** — `HTTPError`는 `URLError`의 서브클래스이므로 반드시 먼저 catch.
   최종 `except Exception`으로 감싸 어떤 경우에도 `False`만 반환하고 호출부를 죽이지 않는다.

4. **`parse_mode` 미사용** — 프로젝트명/경로에 `_`, `*`가 흔해 Markdown/HTML 파싱이 깨진다.
   plain text로만 전송.

5. **`timeout=10` 고정** — 없으면 네트워크 단절 시 MCP 서버 전체가 블록된다.

6. **4096자 truncate** — Telegram API 상한. `send()` 진입 시점에 잘라 400 응답을 예방.

7. **`chat_id`는 str 유지** — 채널(`@channelname`)과 그룹(음수 ID) 모두 지원해야 하므로 `int()` 변환 금지.

8. **`Content-Type: application/json` 명시** — JSON body 사용 시 헤더 없으면 Telegram이 400 반환.

9. **지연 import 유지** — CLI/MCP 모두 함수 내부에서 `from ..plugins.telegram import ...`.
   `commands.py`는 `import os`도 함수 내부에 둬 파일 상단 import 블록 무변경.

10. **MCP `message` 우선 분기** — `message`가 주어지면 DB를 아예 열지 않는다.
    토큰 검증 → message 분기 → (없을 때만) DB 접근 순서라 DB 미존재 환경에서도 동작한다.

11. **에러 처리 비대칭 (의도적)** — CLI는 `console.print("[red]...")` + `sys.exit(1)`,
    MCP는 `"ERROR: ..."` 문자열 반환 (`sys.exit` 금지). 기존 계층 관례와 일치.

12. **환경변수 fallback 우선순위** — CLI/MCP 동일하게 `플래그/인자 > 환경변수 > 에러`.
    `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. 기존 `_default_db()`의 `CPP_ANALYZER_DB` 선례와 동일.

13. **`get_project()`는 `sqlite3.Row | None`** — dict가 아니라 `.get()` 불가.
    `p["name"] if p else f"project#{pid}"`로 방어. 반면 `stats()`는 dict이므로 `format_report`에서 `.get(k, 0)` 사용.

14. **`format_report`에 2번째 상세 줄 추가** — 요청된 기본 포맷
    (`[cpp-analyzer] name` + `Files/Symbols/Calls`)에 `Functions/Classes/Config keys` 한 줄을 덧붙였다.
    전부 `.get(k, 0)` 방어적 접근이라 부분 stats dict에서도 안전.

## 검증 결과

로컬 python에 프로젝트 의존성(click/rich/mcp)이 설치되어 있지 않아
scratchpad에 임시 venv(`uv venv` + `uv pip install -e . "mcp<2" pytest`)를 만들어 실행했다.
프로젝트 트리에는 아무 것도 설치·생성하지 않았다.
(주의: PyPI 최신 `mcp` 2.0.0은 `mcp.server.fastmcp` → `mcp.server.mcpserver`로 경로가 바뀌어
기존 `mcp_server.py`가 import 실패한다. 이번 변경과 무관한 선행 이슈이나 기록해 둔다.)

| 항목 | 결과 |
|------|------|
| `import TelegramNotifier, format_report` | OK |
| `py_compile` × 3파일 | OK |
| `cpp-analyzer notify --help` | OK (`telegram` 서브커맨드 노출) |
| `cpp-analyzer notify telegram --help` | OK (4개 옵션 전부 노출) |
| `cpp-analyzer --help` 최상위 목록 | `notify` 등록 확인 |
| CLI 토큰/chat_id 누락 | 각각 red 메시지 + exit 1 |
| MCP 도구 등록 | 총 19개 tool, `notify_telegram` schema props = `token, chat_id, db_path, project_id, message` |
| MCP 토큰/chat_id 누락 | `ERROR: ...` 문자열 반환 (exit 없음) |
| `send()` 성공 경로 | POST, `Content-type: application/json`, body = `{chat_id, text}`, `parse_mode` 부재, `chat_id`가 str |
| 4096자 truncate | 5000자 입력 → body text 4096자 |
| HTTPError 경로 | `False` 반환, 출력 `[telegram] HTTP 401: Unauthorized`, **토큰 미노출** |
| URLError 경로 | `False` 반환, `[telegram] network error: conn refused` |
| 일반 Exception 경로 | `False` 반환, `[telegram] send failed: ValueError`, **토큰 미노출** |
| `format_report({})` | 빈 stats에서도 0으로 정상 출력 |
| **회귀 테스트** | `pytest tests/ -q` → **112 passed, 1 xfailed, 0 failed** |

실제 네트워크 호출 테스트는 추가하지 않았다 (`urlopen` monkeypatch로만 검증).
`_benchmark_report.json`은 테스트 실행 부산물로 변경되어 `git checkout`으로 원복했다.
