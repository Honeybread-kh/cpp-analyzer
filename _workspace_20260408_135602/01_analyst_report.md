# Analyst Report: index 명령 다중 폴더 지원

## 1. 영향받는 파일과 변경 범위

### 핵심 변경

| 파일 | 변경 범위 | 설명 |
|------|-----------|------|
| `cpp_analyzer/cli/commands.py` | `index` 함수 (line 88-139) | `click.argument("directory")` → 다중 인자 변경 |
| `cpp_analyzer/mcp_server.py` | `index_project` 함수 (line 94-147) | `directory: str` → `directories: list[str]` + 하위호환 |
| `cpp_analyzer/core/indexer.py` | `Indexer.__init__`, `_collect_files` | 단일 `root_path` → 다중 root 지원 |
| `cpp_analyzer/db/schema.py` | `projects` 테이블 | `root_path TEXT NOT NULL UNIQUE` 제약 변경 |
| `cpp_analyzer/db/repository.py` | `upsert_project` | `root_path` → JSON array 저장 |

### 파생 변경

| 파일 | 변경 범위 | 설명 |
|------|-----------|------|
| `cpp_analyzer/analysis/config_dependency.py` | line 49 | `project["root_path"]` 참조 |
| `cpp_analyzer/cli/commands.py` | `_resolve_project`, `report` | `root_path` 표시 부분 |

## 2. 기존 코드 패턴

- CLI: `@click.argument("directory", type=click.Path(exists=True, file_okay=False))`
- MCP: `directory: str` 단일 파라미터
- Indexer: `self.root = Path(root_path).resolve()` 단일 root
- DB: `root_path TEXT NOT NULL UNIQUE`, `ON CONFLICT(root_path)` upsert
- relative_path: `path.relative_to(self.root)`
- files 테이블: `UNIQUE(project_id, relative_path)`

## 3. 의존 관계

```
CLI commands.py ──┐
                  ├──> Indexer(repo, project_id, root_path)
MCP mcp_server.py ┘         │
                             ├──> _collect_files() → os.walk(self.root)
                             ├──> run() → path.relative_to(self.root)
                             └──> repo.upsert_project(name, root_path)
                                         └──> DB: projects(root_path UNIQUE)

config_dependency.py ──> project["root_path"]
commands.py (report, _resolve_project) ──> project["root_path"]
```

## 4. 권장 구현 순서

**접근법: Indexer를 여러 root로 반복 호출, 하나의 project_id에 묶는 방식. root_path를 JSON array로 저장.**

| 순서 | 파일 | 변경 내용 |
|------|------|-----------|
| 1 | `db/schema.py` | `projects.root_path` UNIQUE 제거, SCHEMA_VERSION 5 |
| 2 | `db/repository.py` | `upsert_project` 다중 경로 지원 (JSON array), 조회 시 deserialize |
| 3 | `core/indexer.py` | `root_paths: list[Path]` 지원, `_collect_files()` 다중 root 순회, relative_to 계산 시 소속 root 기준 |
| 4 | `cli/commands.py` | `nargs=-1, required=True` 다중 directory, Indexer에 전달 |
| 5 | `mcp_server.py` | `directories: list[str]` 추가, `directory: str` 하위호환 유지 |
| 6 | `analysis/config_dependency.py` | `root_path` → JSON array 대응 |

## 5. 주의할 엣지 케이스

1. **relative_path 충돌**: 두 디렉토리에 같은 이름 파일 → prefix로 root basename 포함
2. **DB UNIQUE 제약**: `root_path` UNIQUE 제거, 프로젝트 식별을 `name` 기반으로 변경
3. **기존 DB 호환**: 마이그레이션 시 단일 경로를 JSON array로 변환
4. **incremental 인덱싱**: relative_path 체계 변경 시 기존 파일 전체 재인덱싱
5. **MCP 하위호환**: `directory` deprecated 유지 + `directories` 추가
6. **Click nargs=-1**: `required=True` 필요, 뒤에 positional argument 불가
7. **cross-reference**: 폴더 간 include 매칭 시 동명 파일 주의
8. **통계 표시**: 다중 경로 표시 형식 결정
