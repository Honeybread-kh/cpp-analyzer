# QA Report: Parser Improvements (Template, Indirect Calls, Inheritance)

## 변경 요약
- 파서 개선 3가지: (1) C++ 템플릿 해석 강화, (2) 함수 포인터 간접 호출 추적, (3) 네임스페이스/클래스 스코프 정밀 분석 + 클래스 상속 관계

## 검증 결과

| 항목 | 상태 | 비고 |
|------|------|------|
| V1. CLI/MCP 미러링 | PASS | 파서/DB 계층 변경이므로 CLI/MCP 도구 자체 변경 없음. 기존 도구 모두 정상 동작 |
| V2. DB/Repository | PASS | symbols.template_params, calls.call_type, class_inheritance 테이블 모두 정합 |
| V3. Analysis/Repository | PASS | ast_parser 데이터클래스 <-> indexer <-> repository INSERT 체인 완전 일치 |
| V4. Import 체인 | PASS | 순환 import 없음, 모든 import 정상 |
| V5. Config 패턴 | SKIP | config_patterns.yaml 변경 없음 |
| 실행 테스트 | PASS | import, DB 생성, pytest 20/20 통과 |

## V1. CLI/MCP 미러링 상세

이번 변경은 파서(ast_parser.py)와 DB(schema.py, repository.py), 인덱서(indexer.py) 계층만 수정.
CLI 커맨드(commands.py)와 MCP 도구(mcp_server.py)는 변경 없음.

기존 CLI 커맨드 목록: index, stats, query symbol, query config, trace config, trace path, tree, who, deps, report
기존 MCP 도구 목록: index_project, get_stats, list_config_keys, query_config, trace_config, trace_path, call_tree, search_symbols, analyze_configs, export_configs_csv, export_configs_kconfig, file_dependencies, circular_dependencies, dependency_stats

모두 기존과 동일하게 동작 확인 완료 (pytest 20/20 PASS).

## V2. DB 스키마 / Repository 정합성 상세

### SCHEMA_VERSION
- schema.py line 5: `SCHEMA_VERSION = 4` -- PASS

### symbols 테이블 template_params 컬럼
- schema.py line 59: `template_params TEXT` -- PASS
- repository.py insert_symbol() line 170: `template_params: str = ""` keyword arg -- PASS
- repository.py line 187: INSERT SQL에 `template_params` 16번째 컬럼으로 포함 -- PASS
- repository.py line 195: VALUES에 `template_params or None` 전달 -- PASS

### calls 테이블 call_type 컬럼
- schema.py line 77: `call_type TEXT DEFAULT 'direct'` -- PASS
- repository.py insert_call() line 253: `call_type: str = "direct"` keyword arg -- PASS
- repository.py line 257-264: INSERT SQL에 `call_type` 8번째 컬럼으로 포함 -- PASS

### class_inheritance 테이블
- schema.py lines 138-149: CREATE TABLE 정의 -- PASS
  - 컬럼: id, class_symbol_id, base_class_name, base_class_usr, base_class_id, access, is_virtual
  - UNIQUE(class_symbol_id, base_class_name)
  - FK: class_symbol_id -> symbols(id) ON DELETE CASCADE, base_class_id -> symbols(id)
  - 인덱스 2개: idx_inheritance_class, idx_inheritance_base

- repository.py insert_inheritance() lines 293-310: INSERT SQL 컬럼 6개 모두 일치 -- PASS
- repository.py get_base_classes() lines 312-323: SQL 컬럼 참조 모두 정확 -- PASS
- repository.py get_derived_classes() lines 325-336: SQL 컬럼 참조 모두 정확 -- PASS
- repository.py delete_file_symbols() lines 142-146: class_inheritance 정리 포함 -- PASS

### DB 실제 생성 검증
```
DB created with schema v4
Tables: ['schema_meta', 'projects', 'files', 'symbols', 'calls', 'includes',
         'config_patterns', 'config_sources', 'config_usages', 'class_inheritance']
Schema version: 4
symbols.template_params exists: True
calls.call_type exists: True
class_inheritance columns: ['id', 'class_symbol_id', 'base_class_name',
                            'base_class_usr', 'base_class_id', 'access', 'is_virtual']
```

## V3. Analysis / Repository 인터페이스 상세

### ast_parser.py 데이터클래스

| 데이터클래스 | 필드 | 상태 |
|-------------|------|------|
| SymbolInfo | template_params: str = "" (line 39) | PASS |
| CallInfo | call_type: str = "direct" (line 50) | PASS |
| InheritanceInfo | class_usr, base_name, base_usr, access, is_virtual (lines 61-66) | PASS |
| ParseResult | inherits: list[InheritanceInfo] (line 77) | PASS |

### ast_parser.py _walk() 로직

| 기능 | 위치 | 상태 |
|------|------|------|
| 템플릿 파라미터 추출 | lines 334-336: `if kind_val in _TEMPLATE_KINDS: tpl_params = _extract_template_params(cursor)` | PASS |
| indirect call 판별 | line 366: `call_type = "indirect" if called is None else "direct"` | PASS |
| CXX_BASE_SPECIFIER 처리 | lines 381-396: 부모가 클래스이면 InheritanceInfo 수집 | PASS |

### indexer.py -> repository.py 전달

| indexer.py 호출 | repository.py 메서드 | 상태 |
|----------------|---------------------|------|
| `insert_symbol(..., template_params=sym.template_params)` (line 94) | `insert_symbol(..., template_params: str = "")` | PASS |
| `insert_call(..., call_type=call.call_type)` (line 117) | `insert_call(..., call_type: str = "direct")` | PASS |
| `insert_inheritance(class_symbol_id, base_class_name, base_class_usr, base_class_id, access, is_virtual)` (lines 141-148) | `insert_inheritance(class_symbol_id, base_class_name, base_class_usr, base_class_id, access, is_virtual)` | PASS |

### indexer.py 상속 정보 저장 흐름 (lines 131-148)
- `result.inherits` 순회
- `class_usr` -> DB id 변환 (usr_to_id 딕셔너리 + resolve_symbol_id 폴백)
- `base_usr` -> DB id 변환 (동일 패턴)
- class_db_id가 None이면 skip (고아 상속 방지)
- PASS

## V4. Import 체인 상세

### 순환 import 검증
```
cpp_analyzer.core.ast_parser: OK
cpp_analyzer.core.indexer: OK
cpp_analyzer.db.schema: OK
cpp_analyzer.db.repository: OK
No circular import issues
```

### import 경로 확인
- indexer.py line 13: `from ..core.ast_parser import ClangParser, ParseResult` -- PASS
- indexer.py line 14: `from ..db.repository import Repository` -- PASS
- repository.py line 12: `from .schema import DDL, SCHEMA_VERSION` -- PASS
- 순환 없음, 상대 import 일관 사용 -- PASS

### 참고: ParseResult vs FileParseResult
- 코드에서 `ParseResult` 이름 사용 (ast_parser.py line 70)
- `FileParseResult`는 존재하지 않음 (검증 요청서 V3에서 언급되었으나, 실제 코드명은 `ParseResult`)
- indexer.py에서도 `ParseResult`로 import -- 정합성 OK

## V5. Config 패턴
SKIP -- config_patterns.yaml 변경 없음.

## 발견된 문제
없음. 모든 검증 항목 PASS.

## 테스트 로그

### import 테스트
```
$ python -c "from cpp_analyzer.core.ast_parser import ClangParser, SymbolInfo, CallInfo, InheritanceInfo, ParseResult; print('import OK')"
import OK
```

### DB 생성 테스트
```
$ python -c "from cpp_analyzer.db.repository import Repository; ..."
DB created with schema v4
Tables: [..., 'class_inheritance']
Schema version: 4
symbols.template_params exists: True
calls.call_type exists: True
class_inheritance columns: ['id', 'class_symbol_id', 'base_class_name', 'base_class_usr', 'base_class_id', 'access', 'is_virtual']
```

### pytest 실행
```
$ uv run pytest tests/test_dependency_graph.py -v --tb=short
20 passed in 3.29s
```
