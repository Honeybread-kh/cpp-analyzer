# 분석 보고서: 파서 개선 3가지

## 전체 구현 순서

| 순서 | 작업 | 난이도 | DB 변경 |
|------|------|--------|---------|
| 1 | (3-a) 익명 네임스페이스 + namespace_path 확장 | 낮음 | 없음 |
| 2 | (1) 템플릿 해석 강화 (kind 추가 + 파라미터 수집) | 중간 | symbols.template_params 추가 |
| 3 | (3-b) 클래스 상속 관계 수집 | 중간 | class_inheritance 테이블 신설 |
| 4 | (2) 함수 포인터 간접 호출 (Level 1+2) | 중간~높음 | calls.call_type 추가 |

DB 변경을 SCHEMA_VERSION=4로 한번에 묶는다.

## (1) C++ 템플릿 해석 강화

### 현재 상태
- CLASS_TEMPLATE, FUNCTION_TEMPLATE 이미 처리됨 (_CLANG_KIND_MAP에 등록)
- 빠진 것: CLASS_TEMPLATE_PARTIAL_SPECIALIZATION, 템플릿 파라미터 수집, TEMPLATE_REF

### 변경 범위
- ast_parser.py: _CLANG_KIND_MAP에 PARTIAL_SPECIALIZATION 추가, SymbolInfo에 template_params 필드, 파라미터 수집 헬퍼
- schema.py: symbols에 template_params TEXT 컬럼
- repository.py: insert_symbol()에 template_params 추가
- indexer.py: 전달

## (2) 함수 포인터 간접 호출 추적

### 현재 상태
- CALL_EXPR만 처리, cursor.referenced로 해석
- 빠진 것: 간접 호출 구분, 함수 포인터 대입 추적

### Level 1+2까지 구현
- Level 1: CALL_EXPR에서 referenced=None이면 indirect
- Level 2: VAR_DECL에서 함수 포인터 변수 + &func 대입 감지

### 변경 범위
- ast_parser.py: CallInfo에 call_type 필드, _walk() 확장
- schema.py: calls에 call_type TEXT DEFAULT 'direct'
- repository.py: insert_call()에 call_type 추가
- indexer.py: 전달

## (3) 네임스페이스/클래스 스코프 정밀 분석

### (3-a) 익명 네임스페이스 + namespace_path 확장
- _qualified_name(): spelling 비면 "(anonymous)" 삽입
- _namespace_path(): CLASS_DECL/STRUCT_DECL도 포함

### (3-b) 클래스 상속 관계
- CXX_BASE_SPECIFIER 처리 추가
- class_inheritance 테이블 신설
- insert_inheritance(), get_base_classes(), get_derived_classes() 메서드

## DB 스키마 변경 종합

```sql
ALTER TABLE symbols ADD COLUMN template_params TEXT;
ALTER TABLE calls ADD COLUMN call_type TEXT DEFAULT 'direct';

CREATE TABLE IF NOT EXISTS class_inheritance (
    id                INTEGER PRIMARY KEY,
    class_symbol_id   INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    base_class_name   TEXT NOT NULL,
    base_class_usr    TEXT,
    base_class_id     INTEGER REFERENCES symbols(id),
    access            TEXT,
    is_virtual        INTEGER DEFAULT 0,
    UNIQUE(class_symbol_id, base_class_name)
);
```

## 엣지 케이스
- 익명 네임스페이스: 파일+qualified_name 조합으로 유일성 확보
- 템플릿 특수화: USR로 구분, qualified_name에 특수화 인자 포함 여부 결정
- 가상 함수 호출 vs 간접 호출 구분
- CRTP, 다중 상속, inline namespace
- ts_parser.py는 이번 개선과 무관 (C 전용 config 분석 특화)
