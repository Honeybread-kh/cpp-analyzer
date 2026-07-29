# 03 QA Report — Telegram Notification Plugin

브랜치: `claude/install-telegram-plugin-ZlE2C`
검증 일시: 2026-07-29
검증 환경: scratchpad venv (`python3.11` + `-e .` + `mcp<2` + `pytest`) — 프로젝트 트리 무변경

## 결과 요약

| 검증 항목 | 결과 |
|----------|------|
| V1: CLI↔MCP 미러링 | **PASS** |
| V2: DB 계층 사용 | **PASS** |
| V3: Plugin 모듈 독립성 | **PASS** |
| V4: 보안 검증 | **PASS** |
| V5: 실행 테스트 | **PASS** |

FAIL 0건. 배포 차단 이슈 없음. 관찰 사항 3건은 아래 "관찰 사항" 참조 (모두 비차단).

---

## 상세 결과

### V1: CLI ↔ MCP 미러링 — PASS

**대응 관계 확인**

| 계층 | 심볼 | 위치 |
|------|------|------|
| CLI | `notify` 그룹 + `telegram` 서브커맨드 | `cpp_analyzer/cli/commands.py:859-900` |
| MCP | `notify_telegram` tool | `cpp_analyzer/mcp_server.py:1042-1094` |

MCP 서버에 총 19개 tool 등록, `notify_telegram` 포함 확인.
inputSchema properties = `chat_id, db_path, message, project_id, token`, `required: []` (전부 optional).

**파라미터 대응**

| CLI | MCP | 비고 |
|-----|-----|------|
| `--token` | `token` | 일치 |
| `--chat-id` | `chat_id` | 일치 |
| `--project-id` | `project_id` | 일치 |
| `--db` | `db_path` | 프로젝트 전역 관례 (CLI `--db` 14회 / MCP `db_path` 19회) — 정상 |
| — | `message` | MCP 전용. 관찰 사항 #1 |

**환경변수 fallback** — 양쪽 모두 `플래그/인자 > 환경변수 > 에러` 우선순위 실측 확인.

```
CLI precedence: token-in-url=FLAGTOK: True | chat_id: FLAGCID   (env=ENVTOK/ENVCID 무시)
MCP precedence: token-in-url=ARGTOK:  True | chat_id: ARGCID    (env=ENVTOK/ENVCID 무시)
```

`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 모두 CLI(`commands.py:876-877`) · MCP(`mcp_server.py:1065-1066`) 양쪽에서 지원.

**동일 입력 → 동일 결과 (핵심 검증)**
`examples/`를 인덱싱한 실 DB로 4개 경로를 전부 실행하고 전송 payload를 바이트 단위 비교했다.

```
CLI(flags)   exit=0  "Notification sent to Telegram."
CLI(env)     exit=0  "Notification sent to Telegram."
MCP(args)    -> "Notification sent."
MCP(env)     -> "Notification sent."

전송 text:
'[cpp-analyzer] examples\nFiles: 1 | Symbols: 34 | Calls: 26\nFunctions: 12 | Classes: 4 | Config keys: 0'

CLI(flags)   identical-to-CLI(flags): True
CLI(env)     identical-to-CLI(flags): True
MCP(args)    identical-to-CLI(flags): True
MCP(env)     identical-to-CLI(flags): True
→ V1 equivalence: PASS
```

4개 경로가 **완전히 동일한 payload**를 생성. 포맷 차이는 사람이 읽는 콘솔 문구(`"Notification sent to Telegram."` vs `"Notification sent."`)에만 존재 — 허용 범위.

**에러 처리 비대칭 (의도된 설계) 실측**

| 시나리오 | CLI | MCP |
|---------|-----|-----|
| token 누락 | `Telegram bot token required (--token or TELEGRAM_BOT_TOKEN env).` + `exit=1` | `"ERROR: Telegram bot token required (token arg or TELEGRAM_BOT_TOKEN env)."` (SystemExit 없음) |
| chat_id 누락 | `Telegram chat ID required (--chat-id or TELEGRAM_CHAT_ID env).` + `exit=1` | `"ERROR: Telegram chat ID required (chat_id arg or TELEGRAM_CHAT_ID env)."` (SystemExit 없음) |
| `send()` 실패 | `Failed to send Telegram notification.` + `exit=1` | `"ERROR: Failed to send Telegram notification."` (SystemExit 없음) |
| 프로젝트 없음 | `_resolve_project()` → red 메시지 + `exit=1` | `"No project found. Run index_project first."` |

MCP 3개 경로 전부에서 `SystemExit` 미발생 확인 (`try/except SystemExit`로 실측). 기존 계층 관례와 일치.

---

### V2: DB / Repository 계층 사용 — PASS

**MCP: `message` 제공 시 DB 미접근 — 실측 검증**

정적 확인: `message is not None` 분기가 `mcp_server.py:1075`, `_repo()` 호출이 `:1080`.
분기가 DB 접근보다 **앞**에 위치 — 요구사항 충족.

동적 확인: `_repo`를 `side_effect=AssertionError`로 패치하고 존재하지 않는 DB 경로를 넘겨 호출.

```
result: Notification sent.
_repo called: False
sent payload: {"chat_id": "c", "text": "hi"}
→ V2a PASS
```

`db_path='/nonexistent/does_not_exist.db'`인데도 정상 전송. DB를 전혀 열지 않음이 증명됨.

**CLI 헬퍼 사용 및 `repo.close()`**

`commands.py:886-890`:
```
repo = _get_repo(db)
pid  = _resolve_project(repo, project_id)
p    = repo.get_project(pid)
s    = repo.stats(pid)
repo.close()
```

- `_get_repo(db)` (`:58`) — `Repository(db)` + `connect()` 수행. 올바른 사용.
- `_resolve_project(repo, project_id)` (`:64`) — 올바른 사용.
- `repo.close()`가 네트워크 전송(`notifier.send`) **이전**에 호출됨 — 전송 지연 동안 DB 커넥션을 잡고 있지 않아 오히려 기존 커맨드보다 나은 패턴.
- 기존 `stats` 커맨드(`:153-168`)와 구조가 사실상 동일 — 관례 준수 확인.

`commands.py` 전체에 `try/finally`가 0건이고 `_get_repo` 15회 / `repo.close()` 26회로, 직선형 close가 프로젝트 전역 관례다. `_resolve_project()`의 `sys.exit(1)` 경로에서 커넥션이 닫히지 않는 것은 15개 커맨드 전부에 해당하는 기존 관례이며 이번 변경이 도입한 결함이 아니다(관찰 사항 #2).

---

### V3: Plugin 모듈 독립성 — PASS

**AST 기반 import 전수 조사** (`cpp_analyzer/plugins/telegram.py`)

```
imports found: ['__future__', 'json', 'urllib.error', 'urllib.request']
violations: none
→ V3: PASS
```

- `from cpp_analyzer.*` 형태 import: **0건**
- `from ..` / `from .` 상대 import: **0건**
- 허용 stdlib(`json`, `urllib.request`, `urllib.error`) 외 모듈: **0건**
- `from __future__ import annotations`는 모듈 import가 아닌 컴파일러 지시자 — 위반 아님

**런타임 확인** — 플러그인 단독 import 시 적재되는 모듈:
```
cpp_analyzer modules loaded: ['cpp_analyzer', 'cpp_analyzer.plugins', 'cpp_analyzer.plugins.telegram']
heavy deps pulled in: []
```
`click` / `rich` / `mcp` / `sqlite3` / `clang` / `tree_sitter` 전부 미적재. 진성 leaf 모듈이며 순환 import가 구조적으로 불가능하다.

`plugins/__init__.py`는 0바이트 빈 파일 — `find_packages()` 수집용으로 기존 `analysis/`, `db/` 관례와 동일.

---

### V4: 보안 검증 — PASS

**토큰 유출 방지 — 3개 예외 경로 전수 실측**

실제 토큰 문자열(`123456789:AAsecretTOKENvalue_DO_NOT_LEAK`)을 심고, HTTPError의 URL과 generic exception 메시지 **양쪽에 토큰을 일부러 포함**시킨 뒤 stdout+stderr를 캡처해 검사했다.

```
HTTPError  -> returns=False leaked=False out='[telegram] HTTP 401: Unauthorized'
URLError   -> returns=False leaked=False out='[telegram] network error: conn refused'
Generic    -> returns=False leaked=False out='[telegram] send failed: ValueError'
→ V4 leak test: PASS
```

- `HTTPError`: `e.code` / `e.reason`만 사용 (`telegram.py:68`). `str(e)`·traceback 미사용.
- `URLError`: `e.reason`만 사용 (`:71`).
- `Exception`: `type(e).__name__`만 사용 (`:74`) — 메시지에 토큰이 있어도 클래스명만 출력되어 차단됨.
- 예외 순서: `HTTPError` → `URLError` → `Exception` (`:64/70/73`). `HTTPError`가 `URLError` 서브클래스이므로 이 순서가 필수이며 올바르게 지켜짐.
- 세 경로 모두 `False` 반환 — 알림 실패가 호출부를 죽이지 않음.

**payload / 헤더 검증** (mock urlopen으로 실제 `Request` 객체 검사)

```
payload keys: ['chat_id', 'text']
truncation + no parse_mode + Content-Type + POST + timeout=10 OK
```

| 항목 | 결과 |
|------|------|
| `Content-Type: application/json` 헤더 | 존재 (`telegram.py:57`), `req.get_header('Content-type') == 'application/json'` |
| `parse_mode` 미사용 | payload keys가 `['chat_id','text']` — `parse_mode` 부재 확인 |
| timeout 설정 | `urlopen(req, timeout=TIMEOUT)` (`:62`), 실측 `timeout=10` 전달 확인 |
| HTTP method | `POST` |
| `chat_id` 타입 | `str` 유지 (`@channel`·음수 그룹 ID 지원) |

---

### V5: 실행 테스트 — PASS

**1. 회귀 테스트**
```
112 passed, 1 xfailed, 3 warnings in 4.41s
```
developer 보고치(112 passed / 1 xfailed)와 **정확히 일치**. 회귀 0건.
경고 3건은 pytest의 class-scoped fixture deprecation — 이번 변경과 무관한 기존 이슈.

**2. import 체인**
```
plugin import OK
```

**3. CLI 도움말**
```
$ python -m cpp_analyzer notify --help
Commands:
  telegram  Send project analysis summary to a Telegram chat.

$ python -m cpp_analyzer notify telegram --help
Options:
  --db TEXT             [default: cpp_analysis.db]
  --project-id INTEGER
  --token TEXT          Telegram bot token (env: TELEGRAM_BOT_TOKEN)
  --chat-id TEXT        Telegram chat ID (env: TELEGRAM_CHAT_ID)
```
최상위 `--help`에도 `notify` 그룹 노출 확인. 옵션 4개 전부 노출, env 힌트가 help 텍스트에 명시됨.

**4. 에러 경로 (DB 없어도 에러 메시지 출력)**
```
$ TELEGRAM_BOT_TOKEN="" TELEGRAM_CHAT_ID="" python -m cpp_analyzer notify telegram
Telegram bot token required (--token or TELEGRAM_BOT_TOKEN env).
exit=1

$ TELEGRAM_BOT_TOKEN="tok" TELEGRAM_CHAT_ID="" python -m cpp_analyzer notify telegram
Telegram chat ID required (--chat-id or TELEGRAM_CHAT_ID env).
exit=1
```
DB가 없는 디렉토리에서 실행했음에도 자격증명 검증이 DB 접근보다 먼저 일어나 올바른 메시지 출력.

**5. `format_report` 동작**
```
[cpp-analyzer] myproject
Files: 42 | Symbols: 1234 | Calls: 5678
Functions: 0 | Classes: 0 | Config keys: 0
format_report OK
```
요구된 `[cpp-analyzer] myproject` / `Files: 42` assertion 통과. 누락 키는 `.get(k, 0)`으로 0 처리.

**6. Truncation 동작**
```
truncation + no parse_mode + Content-Type OK
```
5000자 입력 → payload text 정확히 `MAX_MESSAGE_LEN`(4096)자. `parse_mode` 부재, `Content-type: application/json` 확인.

**추가: 실 DB end-to-end**
`examples/` 인덱싱(1 files / 38 symbols / 26 calls) 후 CLI·MCP 양쪽 실행 성공, 빈 DB에서는 MCP가 `"No project found. Run index_project first."` 반환.

---

## FAIL 항목

**없음.** V1~V5 전부 PASS.

---

## 관찰 사항 (비차단)

1. **`message` 파라미터가 MCP 전용** — MCP `notify_telegram`은 `message`로 임의 문자열을 보낼 수 있으나 CLI `notify telegram`에는 대응 옵션이 없다. 엄밀한 1:1 미러링 관점에서는 갭이지만, 이번 검증 범위(token/chat_id 플래그·env fallback·에러 처리)는 전부 충족했고 CLI에서는 셸 파이프로 대체 가능하므로 FAIL 처리하지 않았다. 향후 `--message` 옵션 추가를 권장한다.

2. **`_resolve_project()` 조기 종료 시 DB 커넥션 미close** — 프로젝트가 없거나 모호할 때 `sys.exit(1)`이 호출되어 `repo.close()`에 도달하지 않는다. CLI 프로세스가 즉시 종료되므로 실질 영향은 없고, `commands.py`의 15개 커맨드 전부가 동일한 직선형 패턴(파일 내 `try/finally` 0건)이라 이번 변경이 도입한 결함이 아니다. 개선하려면 15개 커맨드 일괄 리팩토링 별건으로 다뤄야 한다.

3. **신규 플러그인에 대한 자동화 테스트 부재** — `tests/` 내 `telegram` 참조 0건. 이번 QA는 임시 스크립트로 검증했으나, 토큰 미유출·4096 truncate·`parse_mode` 부재는 회귀 위험이 있는 보안/프로토콜 계약이므로 `tests/test_telegram.py`로 고정할 것을 권장한다.

## 참고: 환경 이슈 (이번 변경과 무관)

시스템 python에 `mcp`·`pytest` 미설치. `pip install "mcp<2"`는 debian 관리 `PyJWT 2.7.0` 제거 실패로 중단된다(`RECORD file not found`). 시스템 패키지를 건드리지 않기 위해 scratchpad venv를 사용했다. developer가 기록한 대로 PyPI 최신 `mcp` 2.0.0은 `mcp.server.fastmcp` → `mcp.server.mcpserver` 경로 변경으로 `mcp_server.py` import가 깨지므로 `mcp<2` 핀이 필요하다 — 선행 이슈로 별도 트래킹 권장.

프로젝트 트리 변경 없음 (`git status --short` 출력 없음). 테스트 산출물은 전부 scratchpad에 격리했다.
