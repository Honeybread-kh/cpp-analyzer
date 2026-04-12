---
name: cpp-analyzer-evolution
description: "cpp-analyzer의 분석 능력을 벤치마크 기반으로 자동 진화시키는 오케스트레이터. benchmarker로 점수를 측정하고 regression을 감지한 뒤, reasoner로 gap을 코드 수준까지 추론해 제안서를 생성하고, 선택적으로 cpp-analyzer-orchestrator를 재호출해 구현을 진행한다. '진화', '벤치마크 돌려줘', 'evolution', 'gap 분석', '점수 측정', '갭 분석', '분석기 개선 제안', '자동 개선', '진화 파이프라인', 'regression 체크', 'evolve', '진화 돌려줘', '벤치 재실행', '진화 업데이트' 요청 시 트리거. 후속 작업(수정, 다시 실행, 제안 업데이트)에도 이 스킬을 사용."
---

# cpp-analyzer Evolution Orchestrator

cpp-analyzer의 분석 능력을 벤치마크 기반으로 자동 진화시키는 파이프라인.

## 왜 별도 하네스인가

기존 `cpp-analyzer-orchestrator`는 **사용자 지시 기반 개발**(analyst→developer→qa)을 수행한다. evolution은 **자체 측정 기반 자가 개선**이라는 다른 축이다. 목적이 다르므로 에이전트·데이터 경로·실행 주기가 모두 분리되어야 한다. 두 하네스는 독립적으로 운용되며, evolution의 구현 단계에서만 기존 개발 하네스를 재호출한다(implementer=developer 재사용).

## 실행 모드: 서브 에이전트

파이프라인이 순차적(benchmark → reason → implement)이고, 각 단계의 산출물이 파일로 다음 단계에 전달되므로 서브 에이전트 모드가 적합하다.

## 에이전트 구성

| 에이전트 | subagent_type | 역할 | 스킬 | 출력 |
|---------|--------------|------|------|------|
| benchmarker | general-purpose | 벤치마크 실행, regression 감지 | cpp-analyzer-bench | `_workspace_evo/01_benchmark_*` |
| reasoner | general-purpose | gap 분석, 추론, 제안서 작성 | cpp-analyzer-reason | `_workspace_evo/02_reasoner_proposal.md` |
| implementer | (재사용: `cpp-analyzer-orchestrator` 스킬 경유) | 제안된 변경 구현 | cpp-analyzer-dev | 기존 _workspace/ 경로 |

**중요:** implementer는 별도 에이전트가 아니라 **기존 `cpp-analyzer-orchestrator` 스킬을 통째로 호출**하는 방식이다. 즉, evolution-orchestrator가 "이 제안서대로 구현해줘"라는 프롬프트로 cpp-analyzer-orchestrator에 재귀 위임한다.

## 작업 디렉토리

- `_workspace_evo/` — evolution 전용 중간 산출물 (benchmarker, reasoner)
- `_workspace/` — 기존 개발 파이프라인 산출물 (implementer가 재호출되면 여기 사용)

두 경로는 분리되어 서로 덮어쓰지 않는다.

## 워크플로우

### Phase 0: 컨텍스트 확인

1. `_workspace_evo/` 디렉토리 존재 여부 확인
2. 실행 모드 결정:
   - **미존재** → 초기 실행. `mkdir -p _workspace_evo` 후 Phase 1로 진행
   - **존재 + 사용자가 "다시 실행"** → 기존 결과를 `_workspace_evo_{YYYYMMDD_HHMMSS}/`로 보관 후 새 실행
   - **존재 + 사용자가 "제안만 갱신"** → Phase 2부터 실행 (기존 벤치마크 결과 재사용)
   - **존재 + 사용자가 "구현만"** → Phase 3부터 실행 (기존 제안서 기반)
3. 사용자에게 어느 모드로 진입하는지 한 줄 안내

### Phase 1: 벤치마크 측정 (benchmarker)

```
Agent(
  description: "벤치마크 실행 및 회귀 감지",
  prompt: """
  당신은 cpp-analyzer 프로젝트의 벤치마크 측정 전문가입니다.

  `.claude/agents/benchmarker.md`를 읽고 역할과 원칙을 파악하라.
  `.claude/skills/cpp-analyzer-bench/SKILL.md`를 읽고 측정 파이프라인을 파악하라.

  사용자 요청: {user_request}

  다음을 수행하라:
  1. 이전 측정이 있으면 01_benchmark_before.json으로 승격
  2. pytest tests/test_dataflow.py 실행
  3. 결과를 _workspace_evo/01_benchmark_current.json에 집계 저장
  4. _workspace_evo/01_benchmark_report.md에 사람용 요약 작성
  5. regression 있으면 리포트 최상단에 반드시 표시
  """,
  subagent_type: "general-purpose",
  model: "opus"
)
```

### Phase 1.5: Regression 게이트

`_workspace_evo/01_benchmark_report.md`를 Read로 확인한다. 최상단에 `REGRESSION DETECTED`가 있으면:

1. 사용자에게 즉시 보고 (regression 내용 + 어느 테스트가 깨졌는지)
2. Phase 2(reasoner)는 실행하되 **제안은 regression 원인 분석에 집중**하도록 지시
3. Phase 3(implementer)는 **자동 실행 금지** — 사용자 승인 필수

regression이 없으면 정상 진행.

### Phase 2: 추론 및 제안 (reasoner)

```
Agent(
  description: "gap 분석 및 개선 제안",
  prompt: """
  당신은 cpp-analyzer 프로젝트의 분석 추론 전문가입니다.

  `.claude/agents/reasoner.md`를 읽고 역할과 원칙을 파악하라.
  `.claude/skills/cpp-analyzer-reason/SKILL.md`를 읽고 추론 방법론을 파악하라.
  `_workspace_evo/01_benchmark_current.json`과 `_workspace_evo/01_benchmark_report.md`를 읽어라.

  사용자 요청: {user_request}
  Regression 상태: {regression_detected: true/false}

  Gap을 코드 수준까지 추론하고 `_workspace_evo/02_reasoner_proposal.md`에 제안서를 작성하라.
  {create_issue가 true면} gh CLI로 GitHub Issue도 생성하라.
  """,
  subagent_type: "general-purpose",
  model: "opus"
)
```

### Phase 3: 구현 (implementer = cpp-analyzer-orchestrator 재호출)

**자동 실행 조건:**
- regression 없음
- 사용자가 `--auto-implement` 또는 "구현도 진행해줘"를 명시
- 제안서의 최우선 Gap 1건에만 국한 (한 번에 하나씩, 큰 변경은 사람 리뷰)

자동 실행 시:

1. `_workspace_evo/02_reasoner_proposal.md`의 "Gap 1" 섹션을 추출
2. 해당 내용을 프롬프트로 `cpp-analyzer-orchestrator` 스킬을 호출 (재귀 위임)
   - 이 스킬이 analyst→developer→qa 파이프라인을 자체 실행
3. 구현 완료 후 `cpp-analyzer-orchestrator`가 만든 `_workspace/03_qa_report.md`를 읽어 PASS 확인
4. Phase 4로 진행

사용자 승인 모드:
- 제안서 링크와 요약을 사용자에게 보고 후 명시적 승인 대기
- 승인 없으면 Phase 3 생략, Phase 4로 이동

### Phase 4: 재측정 (benchmarker 재호출)

구현이 이뤄졌다면(Phase 3 실행됨) 반드시 다시 benchmarker를 호출해 **점수 변화를 증명**한다.

```
Agent(
  description: "구현 후 벤치마크 재측정",
  prompt: """
  구현이 완료되었다. tests/test_dataflow.py를 다시 실행하여
  점수가 올랐는지, regression이 발생하지 않았는지 확인하라.

  결과는 _workspace_evo/04_benchmark_after.json과
  _workspace_evo/04_benchmark_after_report.md에 저장하라.

  이전(_workspace_evo/01_benchmark_current.json)과의 비교를 포함하라.
  """,
  subagent_type: "general-purpose",
  model: "opus"
)
```

**판정:**
- 점수 상승 + regression 없음 → 성공
- 점수 동일 → 실패 (제안이 효과 없음)
- 점수 하락 또는 regression → **롤백 권고** (사용자에게 git reset 여부 확인)

### Phase 5: 최종 보고

사용자에게 다음을 요약 보고:

```
## Evolution 결과 — {date}

### 측정
- 이전: {score_before}/{max} ({pct_before}%)
- 현재: {score_after}/{max} ({pct_after}%) {delta}

### 제안
- 분석된 gap: {n}
- 주요 카테고리: {categories}
- 제안서 위치: _workspace_evo/02_reasoner_proposal.md

### 구현 (실행된 경우)
- 대상: {gap_name}
- 변경 파일: {file list}
- QA 결과: PASS/FAIL

### 다음 단계
- {권장 사항}
```

## 데이터 흐름

```
사용자 요청
    ↓
[Phase 1: benchmarker] → _workspace_evo/01_benchmark_{current,report}
    ↓
[Phase 1.5: regression 게이트] — 자동 구현 차단 여부 결정
    ↓
[Phase 2: reasoner] → _workspace_evo/02_reasoner_proposal.md (+ 선택: GitHub Issue)
    ↓
[Phase 3: implementer = cpp-analyzer-orchestrator 재귀 호출]
    → _workspace/{01,02,03}_*.md (기존 개발 하네스 산출물)
    ↓
[Phase 4: benchmarker 재호출] → _workspace_evo/04_benchmark_after_*
    ↓
[Phase 5: 최종 보고]
```

## 에러 핸들링

| 상황 | 전략 |
|------|------|
| pytest 실행 실패 | 벤치마크 리포트에 에러 로그 포함, Phase 2 이후 중단, 사용자 알림 |
| regression 감지 | Phase 3 자동 실행 차단. 사용자 승인 필수 |
| reasoner가 "변화 없음" 반환 | Phase 3 건너뛰고 현 상태 보고로 종료 |
| implementer 실패(QA FAIL) | Phase 4 실행하지 말고 _workspace_/03_qa_report.md를 사용자에게 보고, 수동 개입 요청 |
| Phase 4에서 점수 하락 | **롤백 권고**. git status/diff 요약 + reset 여부 확인 |
| 무한 루프 방지 | 한 세션에서 Phase 3 자동 실행은 최대 1회 |

## 제약 조건

- PR 자동 머지 금지 — 반드시 사람 리뷰
- 벤치마크 점수 하락 변경은 자동 적용 금지
- 새 테스트 케이스(expected.yaml) 추가는 자유롭게 허용 (측정 범위 확장은 regression이 아님)
- Phase 3 자동 구현은 "Gap 1건씩" 원칙 — 한 번에 여러 변경 금지

## 트리거 키워드

이 스킬이 반응해야 할 사용자 표현:
- "벤치마크 돌려줘" / "진화 돌려줘" / "evolution"
- "gap 분석해줘" / "점수 어때" / "regression 확인"
- "분석기 개선 제안해줘" / "자동 개선해줘"
- "진화 다시" / "제안 업데이트" / "벤치 재측정"
- "evolve cpp-analyzer" / "run benchmark and propose"

## 테스트 시나리오

### 시나리오 A: 초기 실행 (제안만)
1. 사용자: "cpp-analyzer 벤치마크 돌리고 개선 제안해줘"
2. Phase 0: `_workspace_evo/` 없음 → 초기 실행 모드
3. Phase 1: benchmarker → 점수 71.4%, gap 2개
4. Phase 1.5: regression 없음 (이전 기준점 없음, 초기 실행)
5. Phase 2: reasoner → `02_reasoner_proposal.md` 작성
6. Phase 3: 자동 실행 조건 미충족 → 건너뜀
7. Phase 5: 사용자에게 제안서 링크와 점수 보고

### 시나리오 B: 자동 구현까지
1. 사용자: "진화 파이프라인 돌리고 구현도 자동으로 해줘"
2. Phase 0~2 정상
3. Phase 3: 제안서 최우선 gap 1건을 cpp-analyzer-orchestrator에 재귀 위임
4. Phase 4: 재측정 → 점수 71.4% → 76.2% 상승 확인
5. Phase 5: 성공 보고

### 시나리오 C: Regression 감지
1. 사용자: "진화 다시 돌려줘"
2. Phase 1: 점수 68% (이전 71.4%에서 하락)
3. Phase 1.5: `REGRESSION DETECTED` — Phase 3 자동 차단
4. Phase 2: reasoner가 regression 원인 분석에 집중
5. Phase 5: regression 내용 + 롤백 권고를 사용자에게 보고

### 시나리오 D: 후속 작업 (제안만 갱신)
1. 사용자: "제안서 다시 써줘. 벤치마크는 그대로"
2. Phase 0: `_workspace_evo/` 존재 + "제안만" 요청 → Phase 2부터 실행
3. Phase 2: 기존 `01_benchmark_current.json` 재사용, reasoner 재호출
4. Phase 5: 갱신된 제안서 보고
