# Analyst Report: enum 타입 연결 + config spec 자동 생성

## 요약
- ts_parser.py: extract_enum_definitions() + extract_range_constraints() 추가
- models.py: ConfigFieldSpec dataclass 추가
- taint_tracker.py: _file_enums/_file_ranges 캐시 + generate_config_specs() 메서드
- hw_model.c: enum 패턴 코드 추가 (ExtConfig struct + OpMode/ClkSource enum)
- expected.yaml: enum_tracking 카테고리 3건
- test_dataflow.py: TestEnumTracking + TestConfigSpecGeneration 클래스
- analysis_db fixture의 source_patterns에 ecfg-> 매칭 추가

## 구현 순서
1. ts_parser.py — extract_enum_definitions, extract_range_constraints
2. models.py — ConfigFieldSpec
3. taint_tracker.py — 캐시 + generate_config_specs
4. fixtures + tests

## DB/CLI/MCP 변경 없음
