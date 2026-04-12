# Developer Changes: enum 타입 연결 + config spec 자동 생성

## 수정된 파일 목록

### 1. `cpp_analyzer/analysis/ts_parser.py`
- `extract_struct_fields()`: typedef struct 패턴(`typedef struct { ... } Name;`) 지원 추가. 기존에는 `struct Name { ... }` 형태만 인식했으나, parent가 `type_definition`인 anonymous struct에서 sibling `type_identifier`로 이름을 추출하도록 확장.
- `extract_enum_definitions(root)`: 신규 함수. `enum_specifier` 노드를 순회하여 typedef enum과 named enum을 모두 추출. enumerator 값 auto-increment 지원.
- `_extract_enumerator_values(enum_node)`: 신규 헬퍼. enum body에서 name/value 쌍 추출.
- `extract_range_constraints(root)`: 신규 함수. `if (var < BOUND) var = BOUND;` 패턴에서 min/max constraint 추출.
- `_extract_simple_assignments(node)`: 신규 헬퍼. 단순 assignment의 LHS/RHS 텍스트 추출.

### 2. `cpp_analyzer/analysis/models.py`
- `ConfigFieldSpec` dataclass 추가: field_name, struct_name, field_type, enum_type, enum_values, min_value, max_value, file, line 필드. `to_dict()` 메서드 포함.

### 3. `cpp_analyzer/analysis/taint_tracker.py`
- `__init__`: `self._file_enums`, `self._file_ranges` 캐시 딕셔너리 추가.
- `_load_all_files()`: `extract_enum_definitions()`, `extract_range_constraints()` 호출 및 캐시 저장 추가.
- `generate_config_specs()`: 신규 메서드. struct 필드 목록을 수집하고, enum 타입 매칭 및 range constraint 매칭을 수행하여 `ConfigFieldSpec` 리스트 반환.
- import에 `ConfigFieldSpec` 추가.

### 4. `tests/fixtures/dataflow/hw_model.c`
- `OpMode` typedef enum (MODE_LOW=0, MODE_MED=1, MODE_HIGH=2) 추가
- `ClkSource` named enum (CLK_INT=0, CLK_EXT=1, CLK_PLL=2) 추가
- `ExtConfig` typedef struct (op_mode, clk_src, power_level) 추가
- `enum_config_write()`: ecfg->op_mode/clk_src를 레지스터에 직접 대입
- `enum_range_write()`: ecfg->power_level에 MIN_POWER/MAX_POWER clamp 후 레지스터 대입
- `MIN_POWER`, `MAX_POWER` 매크로 정의

### 5. `tests/fixtures/dataflow/expected.yaml`
- `enum_tracking` 카테고리 3건 추가:
  - `enum config op_mode` (ecfg->op_mode -> regs[MODE_REG], easy)
  - `enum config clk_src` (ecfg->clk_src -> regs[CTRL_REG], easy)
  - `enum range power_level` (ecfg->power_level -> regs[THRESH_REG], easy)

### 6. `tests/test_dataflow.py`
- `analysis_db` fixture: `ext_config_field` source pattern 추가 (`ecfg->(\w+)`)
- `TestEnumTracking` 클래스 (3개 테스트): enum 타입 config 필드의 dataflow 추적 검증
- `TestConfigSpecGeneration` 클래스 (2개 테스트):
  - `test_op_mode_enum_values`: ExtConfig.op_mode의 enum_type/enum_values 검증
  - `test_power_level_range`: ExtConfig.power_level 존재 검증

## 새로 추가된 함수/클래스

| 위치 | 이름 | 타입 |
|------|------|------|
| ts_parser.py | `extract_enum_definitions(root)` | function |
| ts_parser.py | `_extract_enumerator_values(enum_node)` | function (private) |
| ts_parser.py | `extract_range_constraints(root)` | function |
| ts_parser.py | `_extract_simple_assignments(node)` | function (private) |
| models.py | `ConfigFieldSpec` | dataclass |
| taint_tracker.py | `TaintTracker.generate_config_specs()` | method |
| test_dataflow.py | `TestEnumTracking` | test class |
| test_dataflow.py | `TestConfigSpecGeneration` | test class |

## DB 스키마 변경
없음

## 테스트 결과
- 전체 테스트: 46/46 PASS (기존 41 + 신규 5)
- 벤치마크: 45/45 (100%) (기존 42 + 신규 3)
- regression 없음
