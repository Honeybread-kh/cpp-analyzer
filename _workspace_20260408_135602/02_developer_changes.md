# Developer Changes: index 명령 다중 폴더 지원

## 수정된 파일 목록

### 1. `cpp_analyzer/db/schema.py`
- **SCHEMA_VERSION**: 4 → 5
- **projects 테이블**: `root_path TEXT NOT NULL UNIQUE` → `root_path TEXT NOT NULL` (UNIQUE 제거)
- **projects 테이블**: `name TEXT NOT NULL` → `name TEXT NOT NULL UNIQUE` (프로젝트 식별을 name 기반으로 변경)
- `root_path` 컬럼은 JSON array 문자열로 다중 경로를 저장

### 2. `cpp_analyzer/db/repository.py`
- `import json` 추가
- **`upsert_project(name, root_paths)`**: `root_path: str` → `root_paths: str | list[str]` 지원. JSON array로 직렬화하여 저장. `ON CONFLICT(name)` 기반 upsert로 변경.
- **`get_project_root_paths(project_id)`**: 신규 메서드. JSON array를 파싱하여 `list[str]` 반환.
- **`_migrate_to_v5()`**: 신규 메서드. 기존 단일 경로 문자열을 JSON array로 변환하는 마이그레이션.
- **`_apply_schema()`**: v5 미만이면 `_migrate_to_v5()` 실행 후 버전 업데이트.

### 3. `cpp_analyzer/core/indexer.py`
- **`Indexer.__init__`**: `root_path: str | Path` → `root_paths: str | Path | list[str] | list[Path]` 지원. `self.roots: list[Path]` 로 정규화. `self.root` 레거시 호환 유지.
- **`Indexer.run`**: `path.relative_to(self.root)` → `path.relative_to(self._owning_root(path))` 변경.
- **`Indexer._collect_files`**: 단일 root 순회 → `self.roots` 전체 순회.
- **`Indexer._owning_root(path)`**: 신규 메서드. 파일이 속한 root 디렉토리를 반환 (가장 깊은 매칭 우선).

### 4. `cpp_analyzer/cli/commands.py`
- `import json` 추가
- **`index` 커맨드**: `@click.argument("directory")` → `@click.argument("directories", nargs=-1, required=True)` 변경. 다중 디렉토리 지원.
- Indexer 호출 시 `roots` 리스트 전달. `repo.upsert_project`에 리스트 전달.
- 다중 경로 표시 UI 추가.
- **`_resolve_project`**: `root_path` JSON array 표시 대응.
- **`report` 커맨드**: `root_path` JSON array 표시 대응.

### 5. `cpp_analyzer/mcp_server.py`
- **`index_project` 도구**: `directory: str` → `directory: str | None = None` (deprecated, 하위호환). `directories: list[str] | None = None` 추가. 두 파라미터 모두 지원.
- Indexer에 `roots` 리스트 전달. `repo.upsert_project`에 리스트 전달.
- 출력에 다중 경로 정보 표시.

### 6. `cpp_analyzer/analysis/config_dependency.py`
- `import json` 추가
- `project["root_path"]` 참조를 JSON array 디시리얼라이즈로 변경 (`root_paths` 리스트로 변환).

## 신규 함수/메서드

| 위치 | 이름 | 설명 |
|------|------|------|
| `db/repository.py` | `get_project_root_paths(project_id)` | 프로젝트의 root 경로 리스트 반환 |
| `db/repository.py` | `_migrate_to_v5()` | v4→v5 마이그레이션 (단일 경로 → JSON array) |
| `core/indexer.py` | `_owning_root(path)` | 파일이 속한 root 디렉토리 결정 |

## DB 스키마 변경

- `SCHEMA_VERSION`: 4 → 5
- `projects.root_path`: UNIQUE 제약 제거, JSON array 형식으로 저장
- `projects.name`: UNIQUE 제약 추가 (프로젝트 식별 키 변경)
- 마이그레이션: 기존 단일 경로 문자열을 `["path"]` JSON array로 자동 변환
