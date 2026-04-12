# QA Report

## 변경 요약
- `index` 명령이 다중 디렉토리를 지원하도록 전 계층(DB, Core, CLI, MCP, Analysis) 변경. `projects.root_path`를 JSON array로 저장, `projects.name`을 UNIQUE 키로 변경, v4→v5 마이그레이션 추가.

## 검증 결과

| 항목 | 상태 | 비고 |
|------|------|------|
| V1. CLI↔MCP 미러링 | **PASS** (경미한 차이 있음) | 핵심 파라미터 대응 확인. MCP에 `clang_args` 누락은 기존 이슈 |
| V2. DB↔Repository | **PASS** | schema.py DDL과 repository.py SQL 완전 일치 |
| V3. Analysis↔Repository | **PASS** | config_dependency.py의 JSON array 디시리얼라이즈 정상 |
| V4. Import 체인 | **PASS** | 순환 import 없음, 모든 모듈 정상 로딩 |
| V5. Config 패턴 | **SKIP** | config_patterns.yaml 변경 없음 |
| 실행 테스트 | **PASS** | 다중 디렉토리 인덱싱 정상 동작 확인 |

## V1. CLI ↔ MCP 미러링 상세

### index 커맨드 대응

| 기능 | CLI (`index`) | MCP (`index_project`) | 일치 |
|------|--------------|----------------------|------|
| 다중 디렉토리 | `DIRECTORIES` (nargs=-1) | `directories: list[str]` | O |
| 하위호환 단일 경로 | 해당없음 (nargs=-1이 단일도 수용) | `directory: str` (deprecated) | O |
| DB 경로 | `--db` | `db_path` | O |
| 프로젝트 이름 | `--name` | `project_name` | O |
| 강제 재인덱스 | `--force` | `force` | O |
| 패턴 파일 | `--patterns` | 자동 탐지 | 허용 |
| Clang 인자 | `--clang-args` | 없음 | 기존 이슈 |

**결론**: 핵심 다중 디렉토리 기능의 CLI/MCP 미러링은 정상. `clang-args`는 이번 변경과 무관한 기존 누락.

## V2. DB 스키마 ↔ Repository 상세

### schema.py (DDL)
- `projects.name TEXT NOT NULL UNIQUE` -- UNIQUE 추가 확인
- `projects.root_path TEXT NOT NULL` -- UNIQUE 제거 확인 (JSON array 저장)
- `SCHEMA_VERSION = 5` 확인

### repository.py (SQL)
- `upsert_project()`: `ON CONFLICT(name) DO UPDATE SET root_path=excluded.root_path` -- name UNIQUE와 정합
- `json.dumps()` / `json.loads()` 를 통한 JSON array 직렬화/역직렬화 확인
- `get_project_root_paths()`: JSON array 파싱 + 레거시 단일 문자열 fallback 확인
- `_migrate_to_v5()`: 기존 단일 경로 → JSON array 변환 로직 확인
- `_apply_schema()`: `old_version < 5` 일 때 마이그레이션 실행 + 버전 업데이트 확인

**실행 검증**: 마이그레이션 테스트 통과. v4 DB → v5 자동 변환 정상.

## V3. Analysis ↔ Repository 상세

### config_dependency.py
- `project["root_path"]` 접근 후 `json.loads(rp) if rp.startswith("[") else [rp]` 로 JSON array 대응
- `repo.list_files()`, `repo.get_project()`, `repo.search_symbols()`, `repo.get_callers()` 호출 -- 모두 Repository에 존재
- 반환 타입 사용 정상

### commands.py
- `_resolve_project()`: `json.loads(rp) if rp.startswith("[") else rp` 로 표시 대응
- `report()`: 동일한 JSON array 파싱 로직 적용

### indexer.py
- `repo.upsert_project()` 에 `list[str]` 전달 -- Repository 인터페이스와 일치
- `repo.upsert_file()`, `repo.get_file_hash()`, `repo.delete_file_symbols()` 등 기존 메서드 호출 -- 변경 없음

## V4. Import 체인 상세

테스트 커맨드:
```python
from cpp_analyzer.db.schema import SCHEMA_VERSION, DDL
from cpp_analyzer.db.repository import Repository
from cpp_analyzer.core.indexer import Indexer
from cpp_analyzer.cli.commands import cli
from cpp_analyzer.analysis.config_dependency import ConfigDependencyAnalyzer
# → All imports OK
```

- 순환 import 없음
- 새로 추가된 `import json` 은 표준 라이브러리 (repository.py, commands.py, config_dependency.py)
- `__init__.py` 파일은 변경 불필요 (새 모듈 추가 없음, 기존 모듈 내 변경만)

## 실행 테스트 상세

### 1. 기본 도움말
```
$ python -m cpp_analyzer --help
→ 정상 출력. index 커맨드 설명: "Parse and index one or more C++ source directories."
```

### 2. index --help
```
$ python -m cpp_analyzer index --help
Usage: python -m cpp_analyzer index [OPTIONS] DIRECTORIES...
→ DIRECTORIES... (nargs=-1, required=True) 확인
```

### 3. 다중 디렉토리 인덱싱 실행
```
$ python -m cpp_analyzer index /tmp/dir1 /tmp/dir2 --db /tmp/test.db --name multi_test
Project: multi_test  (2 directories)
  /private/tmp/cpp_test_dir1
  /private/tmp/cpp_test_dir2
Indexing complete
  Indexed : 2 files
```
- DB에 root_path가 JSON array `["/private/tmp/cpp_test_dir1", "/private/tmp/cpp_test_dir2"]` 로 저장됨 확인
- 각 파일의 relative_path가 해당 root 기준으로 정확히 계산됨 (`hello.cpp`, `world.cpp`)

### 4. report 커맨드
```
$ python -m cpp_analyzer report --db /tmp/test.db
Root: `/private/tmp/cpp_test_dir1, /private/tmp/cpp_test_dir2`
→ 다중 경로 표시 정상
```

### 5. Repository 단위 테스트
- `upsert_project()` 단일 문자열 / 리스트 입력 모두 정상
- `get_project_root_paths()` JSON array 파싱 정상
- `ON CONFLICT(name)` upsert 동작 정상 (같은 이름 → 같은 ID 반환)
- v4→v5 마이그레이션 자동 실행 정상

### 6. Indexer 단위 테스트
- `_owning_root()` 가장 깊은(가장 구체적인) 루트 선택 정상
- 중첩 디렉토리에서 relative_path 계산 정상

## 발견된 문제

없음. 모든 검증 항목 PASS.

## 참고 사항 (기존 이슈, 이번 변경과 무관)

- MCP 서버에 `clang_args` 파라미터 누락 (기존 이슈)
- `mcp` 패키지가 현재 환경에 설치되어 있지 않아 MCP 서버 직접 실행 테스트는 미수행 (import 수준에서 코드 리뷰로 대체)
