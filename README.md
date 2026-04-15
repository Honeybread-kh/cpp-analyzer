# cpp-analyzer

C/C++ 정적 분석기. 심볼·호출그래프·설정 키·dataflow(taint) 추적을 하나의 SQLite DB에 인덱싱하고, **CLI**와 **MCP server** 두 경로로 조회한다.

주요 특징:

- **libclang** 기반 심볼/호출 그래프 + **tree-sitter** 기반 assignment/dataflow 추출
- **Config 추적**: `getenv` / `FLAGS_*` / `struct_ptr->field = val` 등 regex 패턴으로 설정 키 수집
- **Taint dataflow**: `cfg->field` → 중간 변환 → `REG_WRITE(...)` / `regmap_write(...)` / MMIO까지 inter-procedural 추적
- **Incremental 재인덱싱**: 파일 SHA256 hash 기반 skip. 2회차 이후 parse/taint가 10~30× 빨라지는 `parse_cache` + `trace_result_cache` 내장.
- **CLI ↔ MCP 미러링**: 모든 CLI 커맨드에 대응하는 MCP 툴이 존재.

## Requirements

- Python ≥ 3.9
- libclang (LLVM/Clang)
  - macOS: `brew install llvm`
  - Ubuntu: `sudo apt install libclang-dev`

## Installation

```bash
cd cpp-analyzer
pip install -e .
```

MCP server로 쓰려면:

```bash
pip install mcp
```

## Quick Start

모든 하위 커맨드는 **같은 `--db` 경로**를 공유해야 한다. 한 프로젝트를 분석하는 동안 `--db`는 절대 바꾸지 말 것 (별도 DB면 인덱싱 결과가 보이지 않음).

```bash
# 1) 인덱싱 (최초 1회, 이후 자동 incremental)
cpp-analyzer index ./src --db ./proj.db --name myproj

# 2) 심볼 검색 / 호출 그래프 / dataflow
cpp-analyzer query symbol "parse_header" --db ./proj.db
cpp-analyzer tree "init_device"          --db ./proj.db --direction down --depth 4
cpp-analyzer trace dataflow              --db ./proj.db --save
cpp-analyzer trace query                 --db ./proj.db --source "cfg->" --sink "regs\["
```

## CLI Reference

아래 모든 예시는 `--db <path>` 옵션이 필요하다 (기본값을 쓰고 싶으면 생략 가능하나, 명시 권장).

### `index` — 파싱 & DB 기록

```bash
cpp-analyzer index <dir> [<dir2> ...] \
  --db ./proj.db \
  [--name <project_name>] \
  [--patterns ./config_patterns.yaml] \
  [--force] \
  [--no-cache] \
  [--clang-args "-I./include,-DFOO"]
```

- `--name` 생략 시 첫 디렉토리 이름이 프로젝트명
- `--patterns` config 키 추출 패턴 (아래 "Config pattern YAML" 참조)
- `--force` 변경 없는 파일도 강제 재파싱
- `--no-cache` `parse_cache` / `config_scan_state` 우회 (디버깅용)

파일 hash가 바뀌지 않은 파일은 자동으로 skip → 재실행이 빠르다.

### `query` — 인덱스 조회

```bash
cpp-analyzer query symbol <name> --db ./proj.db [--kind FUNCTION|STRUCT|...] [--limit N]

cpp-analyzer query config --list                --db ./proj.db     # 모든 config 키
cpp-analyzer query config <key>                 --db ./proj.db     # 특정 키의 사용처
```

### `tree` / `who` — 호출 그래프

```bash
cpp-analyzer tree <function> --db ./proj.db --direction down --depth 5   # 호출하는 쪽
cpp-analyzer tree <function> --db ./proj.db --direction up   --depth 4   # 호출되는 쪽

cpp-analyzer who  <function> --db ./proj.db --direction callers
cpp-analyzer who  <function> --db ./proj.db --direction callees --depth 2
```

### `trace config` — config 키 영향 추적

```bash
cpp-analyzer trace config <key> --db ./proj.db --depth 5 --chains 20
```

`key`를 참조하는 조건문에서 출발해 호출 체인을 따라 어디까지 영향이 퍼지는지 보여준다.

### `trace path` — 두 함수 사이 호출 경로

```bash
cpp-analyzer trace path <from> <to> --db ./proj.db [--max-paths 10]
```

### `trace dataflow` — taint / dataflow 분석

```bash
# 기본 패턴 (cfg->field → REG_WRITE/regmap_write/MMIO)
cpp-analyzer trace dataflow --db ./proj.db --save

# YAML 패턴 사용
cpp-analyzer trace dataflow --db ./proj.db --patterns ./patterns/mydriver.yaml --save

# 인라인 regex (일회성)
cpp-analyzer trace dataflow --db ./proj.db \
  --source 'cfg->(\w+)' --sink 'writel\s*\(' --save

# reverse trace (sink 기준 역추적)
cpp-analyzer trace dataflow --db ./proj.db --reverse 'REG_WRITE\s*\('

# JSON 출력
cpp-analyzer trace dataflow --db ./proj.db --format json
```

옵션:
- `--source <regex>` / `--sink <regex>` 반복 지정 가능. 지정하면 해당 축은 완전 대체.
- `--patterns <yaml>` 파일 기반 패턴 로드 (아래 "Dataflow pattern YAML" 참조).
- `--depth <N>` inter-procedural trace 최대 깊이 (default 5).
- `--max-paths <N>` 최대 반환 경로 수 (default 100).
- `--save` 결과를 `dataflow_paths` 테이블에 영속화 → 나중에 `trace query`로 재조회.
- `--no-cache` `parse_cache` / `trace_result_cache` 우회.

### `trace query` — 저장된 dataflow paths 조회

`trace dataflow --save`로 영속화된 결과를 **재분석 없이** DB에서 꺼낸다.

```bash
cpp-analyzer trace query --db ./proj.db \
  --source "cfg->freq" --sink "regs\[" --limit 50 --format tree
```

### `config-spec` — config field spec 추출

struct field별 enum/range/default, register sink, transform을 묶은 CSV/JSON/YAML 출력.

```bash
cpp-analyzer config-spec --db ./proj.db --format csv  --output specs.csv
cpp-analyzer config-spec --db ./proj.db --format yaml --language   # 제약 언어
```

### `stats` / `report`

```bash
cpp-analyzer stats  --db ./proj.db
cpp-analyzer report --db ./proj.db --output report.md
```

### `deps` — include 의존성

```bash
cpp-analyzer deps <file> --db ./proj.db [--direction both|up|down] [--circular]
```

## Config pattern YAML

`index --patterns` 에 넘기는 파일 — **설정 키 이름을 소스 텍스트에서 뽑아내기 위한 regex 카탈로그**.

```yaml
patterns:
  - name: getenv
    type: ENV_VAR
    description: POSIX getenv() call
    regex: 'getenv\s*\(\s*"([^"]+)"'
    key_group: 1

  - name: struct_ptr_assign
    type: STRUCT_FIELD
    description: "ptr->field = value"
    regex: '(\w+)->(\w+)\s*=\s*(.+?)\s*;'
    key_group: 2   # 2번째 캡처그룹 = field 이름을 config_key로 저장
```

- `key_group`: regex의 몇 번째 캡처그룹이 config key인지. 생략 시 1, 0이면 전체 매칭 문자열.
- `type`: `ENV_VAR` / `CLI_ARG` / `GFLAGS` / `STRUCT_FIELD` / `PREPROCESSOR` / `CONFIG_MAP` 등 임의 분류 태그.
- 저장소에 기본 `config_patterns.yaml`이 있으니 그걸 복사해서 프로젝트별로 커스터마이즈.

## Dataflow pattern YAML

`trace dataflow --patterns` / `config-spec --patterns` / `trace_dataflow(patterns_file=...)` 에 넘기는 파일 — **taint의 source와 sink를 정의**.

```yaml
sources:
  - name: config_field
    regex: '(?:cfg|conf|config|param)\w*->(\w+)'

  - name: ioctl_user_arg
    regex: 'user_req->(\w+)'

sinks:
  - name: REG_WRITE
    regex: 'REG_WRITE\s*\(\s*([^,]+)\s*,'

  # MMIO: writel(val, addr) — 값이 0번째 인자
  - name: mmio_writel
    regex: '\b(?:writel|writel_relaxed|__raw_writel|iowrite8|iowrite16|iowrite32)\s*\('
    value_arg: 0

  # regmap 계열: regmap_write(map, reg, val) — 값이 마지막 인자 (기본 동작)
  - name: regmap_write
    regex: '\bregmap_(?:write|update_bits|set_bits|clear_bits|write_bits)\s*\('

  - name: reg_arrow_assign
    regex: '(?:reg|regs|hw_reg|io_regs)\w*->(\w+)\s*='
```

규칙:

- `sources[].regex`의 **첫 캡처그룹**이 source 변수명. 없으면 전체 매칭.
- `sinks[].regex`가 assignment LHS나 call expression에 걸리면 sink.
- `value_arg: N` 은 call-form sink에서 N번째 인자를 taint 값으로 사용. 생략 시 **마지막 인자** 기본값.
- YAML 문자열은 single-quote 권장 (`\w`, `\s` 원문 유지).
- 내장 기본값은 `cpp_analyzer/analysis/taint_tracker.py`의 `DEFAULT_SOURCE_PATTERNS` / `DEFAULT_SINK_PATTERNS` 참고.

## MCP Server

### 설정

`.mcp.json` 예시:

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "cpp-analyzer-mcp"
    }
  }
}
```

`pip install -e .` 후에는 `cpp-analyzer-mcp` 엔트리포인트를 바로 쓸 수 있다. Python 모듈로 기동하려면:

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "python",
      "args": ["-m", "cpp_analyzer.mcp_server"],
      "cwd": "/abs/path/to/cpp-analyzer"
    }
  }
}
```

DB 경로는 툴 호출 시 `db_path` 파라미터로 넘기거나 환경변수로 고정.

### MCP Tools

| Tool | 역할 |
|------|------|
| `index_project` | 소스 디렉토리 인덱싱 (다른 툴 전에 필수) |
| `search_symbols` | 이름/종류로 심볼 검색 |
| `call_tree` | 함수의 호출 트리 (down/up) |
| `trace_path` | 두 함수 사이 호출 경로 |
| `trace_config` | config 키가 활성화하는 호출 체인 |
| `query_config` | config 키 사용처 + 제어 흐름 영향 |
| `list_config_keys` | 수집된 모든 config 키 |
| `analyze_configs` | struct-field 기반 config 의존성 분석 |
| `export_configs_csv` / `export_configs_kconfig` | config 분석 결과 export |
| `trace_dataflow` | taint dataflow (forward). `save=True`로 DB 영속화. |
| `reverse_trace_dataflow` | sink 기준 역 taint |
| `query_dataflow_paths` | 저장된 dataflow_paths 재조회 (재분석 X) |
| `export_config_spec` | struct field spec (enum/range/sink) CSV/JSON/YAML |
| `file_dependencies` / `circular_dependencies` / `dependency_stats` | include 의존성 |
| `get_stats` | 프로젝트 인덱싱 통계 |

### 전형적인 MCP 흐름

```
index_project(directory="/abs/src", db_path="/abs/proj.db", name="myproj")
trace_dataflow(db_path="/abs/proj.db", patterns_file="/abs/patterns/myproj.yaml", save=True)
query_dataflow_paths(db_path="/abs/proj.db", source_var="cfg->", sink_var="regs[", limit=50)
```

## Caching Model

세 종류의 hash-keyed 캐시가 반복 분석 비용을 제거한다. 모두 파일 hash가 바뀌면 자동 무효화.

| 캐시 | 스코프 | 키 | 무효화 |
|------|--------|-----|--------|
| `parse_cache` | 파일당 tree-sitter 추출 결과 | `(file_id, file_hash)` | 파일 hash 변경 or FK cascade |
| `config_scan_state` | 파일당 config regex 스캔 상태 | `(file_id, scan_hash)` | 파일 hash 변경 |
| `trace_result_cache` | trace() 쿼리 결과 | `(project_id, pattern_hash, project_fingerprint)` | 파일 하나라도 hash 변경 시 fingerprint 불일치로 무효 |

`--no-cache` / `use_cache=False` 로 전부 우회 가능.

## 한계

- **C 순수 프로젝트**: libclang의 C++ 파서를 쓰므로 일부 파싱 오류 발생 가능 (분석 결과에 미치는 영향은 제한적).
- **함수 포인터**: 배열 / struct member / 로컬 별칭 기반 dispatch는 다수 추적하지만, 완전한 indirect call 해소는 불가능.
- **매크로 확장**: 복잡한 매크로 체인은 부분적으로만 추적됨.

## Project Layout

```
cpp-analyzer/
├── cpp_analyzer/
│   ├── __main__.py
│   ├── mcp_server.py          # FastMCP 서버
│   ├── cli/commands.py        # click CLI
│   ├── core/
│   │   ├── indexer.py         # 인덱싱 파이프라인 (incremental)
│   │   └── ast_parser.py      # libclang 래퍼
│   ├── analysis/
│   │   ├── call_graph.py
│   │   ├── path_tracer.py
│   │   ├── config_tracker.py  # config 키 추출
│   │   ├── taint_tracker.py   # dataflow/taint 엔진 + 기본 패턴
│   │   ├── ts_parser.py       # tree-sitter 기반 assignment/range/enum 추출
│   │   └── models.py          # ConfigParam / ConfigFieldSpec / DataFlowPath
│   └── db/
│       ├── schema.py          # SCHEMA_VERSION, CREATE TABLE
│       └── repository.py      # 모든 DB 접근 함수
├── tests/
│   ├── test_dataflow.py       # fixture 기반 벤치마크 테스트
│   ├── test_parse_cache.py    # 캐시 계층 유닛 테스트
│   └── fixtures/dataflow/
├── scripts/
│   ├── bench_parse_cache.py
│   └── profile_trace.py
├── config_patterns.yaml       # 기본 config 키 패턴
└── pyproject.toml
```
