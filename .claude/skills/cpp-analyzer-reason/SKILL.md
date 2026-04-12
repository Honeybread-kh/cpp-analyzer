---
name: cpp-analyzer-reason
description: "cpp-analyzer의 벤치마크 gap을 분석하여 '왜 놓쳤는지'와 '어떻게 개선할지'를 코드 수준(파일명:함수명)으로 추론하는 스킬. gap 카테고리(inter_procedural, alias_tracking, macro_sink 등)별로 taint_tracker.py, ts_parser.py의 관련 함수를 추적하고, 최소 변경 제안과 GitHub Issue 본문을 생성한다. reasoner 에이전트가 사용. 분석 갭 분석, 진화 제안, 미탐 원인 분석, evolution 파이프라인의 추론 단계에서 트리거."
---

# cpp-analyzer Reasoning Skill

벤치마크 gap을 보고 "왜 못 잡는가 → 어떻게 고치는가"를 추론하는 방법론.

## 왜 이 스킬이 필요한가

"점수가 71%다"는 정보만으로는 개선 방향을 알 수 없다. reasoner가 gap을 코드 레벨로 분해하지 않으면, implementer는 추측으로 리팩토링을 시작하고 결국 regression을 만든다. 이 스킬은 **추상적 조언 금지**와 **근거 기반 제안**을 강제한다.

## 핵심 원칙

1. **추상 금지** — "알고리즘 개선", "분석 강화" 같은 표현은 가치가 없다. 항상 `파일:함수` 수준으로 내려간다
2. **코드 직접 인용** — 원인 가설을 세울 때 관련 함수를 Read로 열고 실제 라인을 인용한다
3. **최소 변경 선호** — 재설계보다 "한 if 가지 추가"로 해결되는지 먼저 확인
4. **반복 제안 방지** — 이전 제안서(`02_reasoner_proposal.md`)를 읽고 같은 gap에 같은 제안을 반복하지 않는다
5. **regression은 최우선** — 벤치마크 리포트에 `REGRESSION DETECTED`가 있으면 신규 기능 제안 중단하고 regression 원인 분석 먼저

## 입력

- `_workspace_evo/01_benchmark_current.json` (필수)
- `_workspace_evo/01_benchmark_report.md`
- (선택) `_workspace_evo/02_reasoner_proposal.md` — 이전 제안

## 분석 절차

### Step 1: Gap 카테고리 분류

`by_requires` 집계에서 합격률 낮은 카테고리를 우선순위화:

```
basic: 100%           ← 안정
alias_tracking: 100%  ← 안정
inter_procedural: 0%  ← 집중 공략
macro_sink: 100%      ← 안정
```

0% 또는 50% 미만 카테고리가 최우선 분석 대상.

### Step 2: 테스트 패턴 실물 확인

gap이 있는 카테고리에 대해:

1. `tests/fixtures/dataflow/expected.yaml`에서 해당 `requires:` 를 가진 엔트리 찾기
2. `tests/fixtures/dataflow/hw_model.c`에서 해당 패턴의 실제 C 코드 확인
3. 패턴을 한 문장으로 요약 (예: "함수 A가 config->x를 읽어 반환하고, 호출자 B가 그 반환값을 reg에 쓰는 패턴")

### Step 3: 현재 탐지 로직 추적

다음 순서로 코드를 읽는다:

1. `cpp_analyzer/analysis/taint_tracker.py::trace` — 진입점
2. `taint_tracker.py::_trace_backward` — 재귀 역추적
3. `taint_tracker.py::_find_reaching_defs` — 변수의 이전 할당 찾기
4. `taint_tracker.py::_find_callers_with_args` — 인터프로시저 확장
5. `cpp_analyzer/analysis/ts_parser.py::extract_all_assignments` — 파서 레벨 패턴 추출

각 함수에서 "해당 gap 패턴이 어느 분기에서 매칭 실패하는지" 특정한다.

### Step 4: 원인 가설 수립

다음 포맷으로 작성:

```
- **현상:** X 패턴이 MISS
- **예상 경로:** _trace_backward가 변수 v를 찾기 위해 _find_reaching_defs를 호출
- **실패 지점:** _find_reaching_defs는 assignment_expression만 검사. return value 흐름은 무시
- **근거 코드:** taint_tracker.py:L187 `for a in assignments: if a["lhs"] == var ...`
```

### Step 5: 최소 변경 제안

제안은 다음 3단계로 나눈다:

| 단계 | 설명 | 예시 |
|------|------|------|
| **Tier 1: 파서 확장** | ts_parser에서 새 노드 타입 추출 | `extract_return_statements()` 추가 |
| **Tier 2: DB 확장** | 스키마에 새 테이블/컬럼 | `function_returns` 테이블 |
| **Tier 3: 분석 로직** | taint_tracker에 새 분기 | `_trace_backward`에 "return value" 케이스 |

Tier가 낮을수록 영향 범위가 작다. Tier 3만으로 해결되면 Tier 1/2는 생략.

### Step 6: 부작용 검토

제안 변경이 현재 통과 테스트를 깨뜨릴 가능성:

- 새 분기가 기존 매칭보다 **먼저** 실행되면 위험 (우선순위 반전)
- 재귀 깊이가 늘어나면 무한루프 위험 — visited set 확인
- 기존 통과 테스트의 requires 카테고리를 훑고 교차 영향 없는지 확인

## 출력 구조

`_workspace_evo/02_reasoner_proposal.md`:

```markdown
# Evolution Proposal — {date}

## 현재 상태
- 점수: {score}/{max} ({pct}%)
- 주요 gap: {category list}
- {REGRESSION DETECTED 있으면 여기 명시}

## Gap 분석

### Gap 1: {name}
- **요구 능력:** {requires}
- **패턴 실물:** {from hw_model.c, ~5줄 인용}
- **원인 가설:** {Step 4 포맷}
- **제안 변경:**
  - Tier X: {구체적 함수/변경}
  - 예상 LOC: ~{N}줄
- **부작용 검토:** {Step 6 결과}
- **예상 난이도:** 하/중/상

### Gap 2: ...

## 신규 테스트 케이스 제안
{expected.yaml에 추가할 패턴 — 있으면}

## 우선순위
1. (최우선) ...
2. ...

## 비권장 사항
{건드리지 말아야 할 것}
```

## GitHub Issue 생성 (선택)

사용자가 `--create-issue` 모드로 요청하면:

```bash
gh issue create \
  --title "cpp-analyzer evolution: {gap_category}" \
  --body-file _workspace_evo/02_reasoner_proposal.md \
  --label "enhancement,auto-evolution"
```

이슈 번호를 `_workspace_evo/02_reasoner_issue.txt`에 기록.

## 품질 체크리스트

제안서 완성 전 확인:

- [ ] 모든 gap에 대해 "파일:함수" 수준 근거 포함
- [ ] 코드 인용이 최소 1개 이상
- [ ] Tier별 제안이 구분되어 있음
- [ ] 부작용 검토 섹션 있음
- [ ] 이전 제안과의 차이 (재호출 시)
- [ ] 우선순위가 숫자로 명시됨
