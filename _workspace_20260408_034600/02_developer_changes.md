# Developer Changes: 파서 개선 3가지

## 수정된 파일

### 1. `cpp_analyzer/db/schema.py` (기존 완료)
- SCHEMA_VERSION 4
- `symbols` 테이블에 `template_params TEXT` 컬럼
- `calls` 테이블에 `call_type TEXT DEFAULT 'direct'` 컬럼
- `class_inheritance` 테이블 신설 (class_symbol_id, base_class_name, base_class_usr, base_class_id, access, is_virtual)

### 2. `cpp_analyzer/db/repository.py` (기존 완료)
- `insert_symbol()`: `template_params` keyword argument 추가
- `insert_call()`: `call_type` keyword argument 추가
- `insert_inheritance()`: 신규 메서드
- `get_base_classes(symbol_id)`: 부모 클래스 목록 조회
- `get_derived_classes(symbol_id)`: 자식 클래스 목록 조회
- `delete_file_symbols()`: class_inheritance 테이블 정리 포함

### 3. `cpp_analyzer/core/ast_parser.py` (수정)
**(1) 템플릿 해석 강화:**
- `_CLANG_KIND_MAP`에 `CLASS_TEMPLATE_PARTIAL_SPECIALIZATION` 등록 (기존 완료)
- `_SYMBOL_KINDS`, `_CLASS_KINDS`, `_TEMPLATE_KINDS`에 추가 (기존 완료)
- `SymbolInfo.template_params` 필드 (기존 완료)
- `_extract_template_params()` 헬퍼 함수 (기존 완료)
- **`_walk()`에서 심볼 수집 시 `_TEMPLATE_KINDS`이면 `_extract_template_params()` 호출하여 `template_params` 설정** (신규)

**(2) 함수 포인터 간접 호출:**
- `CallInfo.call_type` 필드 (기존 완료)
- **`_walk()`의 CALL_EXPR에서 `cursor.referenced`가 None이면 `call_type="indirect"` 설정** (신규)

**(3-a) 네임스페이스/클래스 스코프:**
- `_qualified_name()`: 익명 네임스페이스 `(anonymous)` 처리 (기존 완료)
- `_namespace_path()`: CLASS_DECL, STRUCT_DECL, CLASS_TEMPLATE도 스코프 경로에 포함 (기존 완료)

**(3-b) 클래스 상속 관계:**
- `InheritanceInfo` 데이터클래스 (기존 완료)
- `ParseResult.inherits` 필드 (기존 완료)
- **`_walk()`에서 `CXX_BASE_SPECIFIER` 처리 추가 - 부모 cursor가 클래스면 상속 정보 수집** (신규)

### 4. `cpp_analyzer/core/indexer.py` (수정)
- **`insert_symbol()` 호출에 `template_params=sym.template_params` 전달** (신규)
- **`insert_call()` 호출에 `call_type=call.call_type` 전달** (신규)
- **상속 정보 저장: `result.inherits` 순회하여 `repo.insert_inheritance()` 호출** (신규)

## DB 스키마 변경
- SCHEMA_VERSION: 4
- symbols.template_params TEXT (신규 컬럼)
- calls.call_type TEXT DEFAULT 'direct' (신규 컬럼)
- class_inheritance 테이블 (신규)

## 신규 추가된 함수/클래스
- `ast_parser._extract_template_params(cursor) -> str`
- `ast_parser.InheritanceInfo` dataclass
- `repository.insert_inheritance()`
- `repository.get_base_classes()`
- `repository.get_derived_classes()`
