---
name: cpp-analyzer-triage
description: "miner가 채굴한 idiom 후보를 DUP/NOISE/NOVEL로 분류하고 novelty_score를 부여하는 방법론. 기존 fixture set의 kind 인덱스를 만들어 중복을 걸러내고, taint source/sink가 불명확하거나 trivial한 후보를 NOISE로 드랍하며, NOVEL 후보는 novelty_score 1-5와 est_difficulty를 태깅해 우선순위화한다. triager 에이전트가 사용."
---

# cpp-analyzer Triage Skill

miner의 raw 후보에서 "실제로 fixture화할 가치가 있는 것"만 골라내는 분류 규칙.

## 왜 이 스킬이 필요한가

miner는 패턴 매칭만 하므로 기존 fixture와 겹치는 것, trivial한 것, 우리가 분석 불가능한 것이 섞인다. 사용자에게 10+ 후보를 그대로 제시하면 선택 비용이 커지고 fixture 품질이 떨어진다. 이 스킬은 **3단 필터**로 sig/noise를 분리한다.

## 입력

- `_workspace_curator/01_mining_candidates.json` — miner 산출물
- `tests/fixtures/dataflow/expected.yaml` — 기존 fixture 인덱스
- `tests/fixtures/dataflow/*.c` (필요 시)

## 분류 절차

### Step 1 — 기존 fixture kind 인덱스 구축

`expected.yaml`의 모든 엔트리를 읽고 `requires:` 태그를 집계:

```
existing_kinds = {
  "basic", "inter_procedural", "alias_tracking",
  "fnptr_indexed_table", "container_of_alias", "goto_reaching_def",
  "memcpy_bulk_copy", "mmio_accessor", "designated_init",
  "fnptr_local_alias", "is_err_guard", "forward_wrapper",
  ...
}
```

추가로 `.c` fixture 파일명을 스캔해 `kind_tag` 매핑 확인.

### Step 2 — DUP 필터

각 후보 c에 대해:

```
if c.kind in existing_kinds:
    if taint_topology(c) == taint_topology(existing_fixture[c.kind]):
        c.verdict = DUP
        continue
    # kind는 같지만 변형 — NOVEL 가능성 있음, 다음 단계로
```

**topology 비교 기준:**
- source 종류 (struct field / function return / global / param)
- sink 종류 (register array / MMIO accessor / macro sink)
- 중간 hop 수 (직접 / 1-hop / multi-hop)
- 조합 패턴 (single kind / combinatorial)

### Step 3 — NOISE 필터

NOISE 판정 조건 (OR):
- taint source 식별 불가 (예: 하드코딩 상수만)
- sink가 분석 범위 밖 (예: inline asm, syscall 번호)
- 함수 본문 ≤3줄 trivial
- 매크로 확장 없이 의미 파악 불가
- 테스트 코드 / docs / auto-generated 파일

### Step 4 — NOVEL 점수 부여

| 점수 | 기준 |
|------|------|
| 5 | 완전 새로운 축 (예: linked-list walk, weak-symbol callback registry) |
| 4 | 기존 축 2개 결합 (예: container_of + goto unwind) |
| 3 | 기존 축의 새 variant (예: 3-hop forwarding) |
| 2 | 기존 축의 미세 변형 (예: volatile 키워드 추가) |
| 1 | 거의 DUP에 가까움 |

est_difficulty: easy / medium / hard (분석기 대응 난이도 추정).

## 출력

`_workspace_curator/02_triage_report.md` — triager 에이전트 정의에 템플릿 있음.

## 가중 순위 공식

```
priority = novelty_score * difficulty_weight
difficulty_weight: easy=1, medium=2, hard=3
```

같은 점수면 combinatorial bonus(다른 kind와 결합)가 있는 후보 우선.

## 에러 핸들링

- 후보 JSON 파싱 실패 → miner 재실행 요청
- 기존 fixture 목록 구축 실패 → 모든 후보 NOVEL 처리하지 말고 오류 보고
- NOVEL 0건 → "신규 idiom 없음" 명시, Phase 3 호출 불필요

## 반복 실행

이전 `02_triage_report.md`에서 NOVEL 추천했으나 fixture로 안 만든 후보는 다시 제시하지 말 것 (사용자가 의도적으로 드랍했을 수 있음).
