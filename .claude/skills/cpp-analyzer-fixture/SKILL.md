---
name: cpp-analyzer-fixture
description: "NOVEL idiom 후보를 최소 재현 C fixture로 번역하는 스킬. 원본 저작권/식별자를 rename하여 라이선스-safe하게 재작성하고, tests/fixtures/dataflow/*.c + expected.yaml + tests/test_dataflow.py 에 일관된 스타일로 엔트리를 추가한다. fixture-writer 에이전트가 사용."
---

# cpp-analyzer Fixture Writing Skill

curator 파이프라인의 산출물 — 새로운 benchmark fixture를 작성하는 규약.

## 왜 이 스킬이 필요한가

fixture는 evolution의 "진실의 원천"이다. 스타일이 들쭉날쭉하면 분석기 테스트가 부서지고, 라이선스 이슈가 있으면 프로젝트 전체가 오염된다. 이 스킬은 **네이밍·라이선스·테스트 패턴**을 강제한다.

## 원본 재작성 규칙 (라이선스-safe)

1. 저작권 주석, SPDX 태그, 원본 파일명 복사 금지
2. 함수명·타입명·매크로명 모두 rename
   - `struct ad7476_state` → `CxCfg`
   - `ad7476_probe` → `cx_probe`
   - `AD7476_SAMPLE_REG` → `CX_SAMPLE_REG`
3. 도메인 식별자(드라이버명·하드웨어명·제조사명) 중립화
4. 주석은 idiom 설명 1-2줄만, 원본 코멘트 인용 금지
5. 의존 헤더 최소화 — `<stdint.h>`만 허용 (uint32_t 등). kernel 헤더 포함 금지

## 파일 네이밍

- `.c`: `{idiom_tag}_{variant}.c` — 소문자·언더스코어 (예: `linked_list_walk.c`)
- prefix `Cx` / `cx_` — curator 유래 fixture 격리
- expected.yaml 내 `requires:` 태그는 idiom_tag와 동일

## fixture `.c` 템플릿

```c
/**
 * C{N} fixture: <한 줄 idiom 설명>.
 * Why challenging: <분석기가 놓칠 수 있는 이유 한 줄>.
 */

#include <stdint.h>
typedef uint32_t u32;

typedef struct { u32 field; } CxCfg;
typedef struct { u32 regs[8]; } CxRegs;

#define CX_REG 0

/* <30-60 줄의 재현된 idiom> */
```

## expected.yaml 추가 섹션

파일 맨 끝 (`# Scoring:` 주석 바로 위)에 추가:

```yaml
  # ══════════════════════════════════════════════════════
  # C{N}: <idiom 한 줄 설명>
  # ══════════════════════════════════════════════════════

  - name: "<idiom_tag> <variant>"
    source: "<cfg->field>"
    sink: "<REG 또는 sink_fn>"
    expected_function: "<sink이 있는 함수>"
    requires: <idiom_tag>
    min_depth: <정수>
    difficulty: hard
```

## test class 템플릿

`tests/test_dataflow.py`의 `TestAliasingAdvanced` 앞에 삽입:

```python
class TestC{N}{IdiomName}:
    """C{N}: <idiom 설명> — curator-mined frontier."""

    def test_{variant}(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("<cfg->field>" in p.source.variable
                    and "<REG>" in p.sink.variable
                    and p.sink.function == "<expected_function>"):
                return
        pytest.fail("C{N} <variant> — frontier not yet covered")
```

## FAIL이 정상인 이유

curator의 목적은 **측정 범위 확장**이다. 신규 fixture가 현재 분석기로 FAIL 하면:
- evolution 파이프라인의 다음 cycle에서 reasoner가 이 gap을 분석
- implementer가 gap을 메우는 변경을 제안/적용
- 다음 재측정에서 PASS로 전환 → 점수 상승

즉 FAIL은 "분석기의 다음 목표"를 드러내는 신호.

## 실행 전 체크리스트

- [ ] 원본의 어떤 요소도 문자 그대로 복사하지 않았다
- [ ] `Cx` prefix가 기존 fixture와 충돌하지 않는다 (`grep -r "Cx" tests/fixtures/dataflow/`)
- [ ] expected.yaml 문법 유효 (YAML 파싱)
- [ ] test class 이름이 기존 클래스와 충돌하지 않는다
- [ ] `pytest tests/test_dataflow.py::TestC{N}...` 가 import 에러 없이 실행된다 (FAIL은 OK)

## 출력

- 신규 `.c` fixture (tests/fixtures/dataflow/)
- `expected.yaml` 수정
- `tests/test_dataflow.py` 수정
- `_workspace_curator/03_fixture_additions.md` — 추가 요약

## 에러 핸들링

- Cx prefix 충돌 → 다음 번호로 증가 (C01, C02, ...)
- YAML 파싱 실패 → rollback, 오케스트레이터 보고
- test import 에러 → 해당 fixture 전체 rollback
