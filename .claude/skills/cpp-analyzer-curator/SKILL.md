---
name: cpp-analyzer-curator
description: "실 OSS C/C++ 저장소에서 taint/dataflow idiom을 채굴하여 cpp-analyzer benchmark fixture로 편입하는 오케스트레이터. miner로 후보 수집 → triager로 DUP/NOISE/NOVEL 분류 → 사용자 승인 → fixture-writer로 최소 재현 fixture 작성 → benchmarker로 프런티어 확인. 새 fixture가 FAIL이면 'Frontier Detected' 신호로 evolution 파이프라인 입력이 됨. 'fixture 채굴', 'curator 돌려줘', '실 커널에서 패턴 가져와', '새 프런티어 찾아줘', '벤치마크 fixture 확장', 'mine fixtures' 등에서 트리거."
---

# cpp-analyzer Fixture Curator Orchestrator

cpp-analyzer의 **측정 범위**를 넓히는 자가 확장 파이프라인.

## 왜 별도 하네스인가

- `cpp-analyzer-orchestrator` (개발): 사용자 지시에 따른 기능 구현
- `cpp-analyzer-evolution` (자가 개선): 기존 fixture에서 gap을 찾아 메움
- **`cpp-analyzer-curator` (측정 확장): 외부 코드에서 새 idiom을 찾아 fixture를 넓힘**

Evolution은 "fixture 기준 점수"를, curator는 "fixture의 대표성"을 다룬다. 직교하므로 별도 하네스.

## 실행 모드: 서브 에이전트

miner → triager → (사용자 승인) → fixture-writer → benchmarker 순차 파이프라인. 각 단계 산출이 파일로 다음에 전달되므로 서브 에이전트 모드.

## 에이전트 구성

| 에이전트 | subagent_type | 역할 | 스킬 | 출력 |
|---------|--------------|------|------|------|
| miner | general-purpose | 외부 repo shallow clone + 휴리스틱 채굴 | cpp-analyzer-mine | `_workspace_curator/01_mining_candidates.json` |
| triager | general-purpose | DUP/NOISE/NOVEL 분류 + novelty score | cpp-analyzer-triage | `_workspace_curator/02_triage_report.md` |
| fixture-writer | general-purpose | 최소 재현 `.c` + yaml + test 작성 | cpp-analyzer-fixture | tests/fixtures/dataflow/ 업데이트, `_workspace_curator/03_fixture_additions.md` |
| benchmarker (재사용) | general-purpose | 추가 후 측정 | cpp-analyzer-bench | `_workspace_curator/04_frontier_check.md` |

## 작업 디렉토리

- `_workspace_curator/` — 이 하네스 전용
- `/tmp/curator_sources/<repo>/` — 외부 repo sandbox (프로젝트 repo 건드리지 않음)
- `_workspace/`, `_workspace_evo/` 는 touch 금지

## 워크플로우

### Phase 0: 컨텍스트 확인

1. `_workspace_curator/` 존재 여부 확인
2. 사용자 요청에서 target repo 추출:
   - 명시 제공 (git URL 또는 로컬 경로): 그대로 사용
   - 미제공: 기본 후보 제시 — `torvalds/linux:drivers/iio/` / `zephyrproject-rtos/zephyr` / 사용자 최근 프로젝트
3. 기존 실행 있으면 `_workspace_curator_{YYYYMMDD_HHMMSS}/`로 보관
4. 한 줄로 모드 안내

### Phase 1: 채굴 (miner)

```
Agent(
  description: "외부 OSS idiom 채굴",
  prompt: """
  당신은 cpp-analyzer curator 파이프라인의 miner 에이전트입니다.

  `.claude/agents/miner.md`를 읽고 역할·원칙을 파악하라.
  `.claude/skills/cpp-analyzer-mine/SKILL.md`를 읽고 휴리스틱 카탈로그를 파악하라.

  Target repos: {target_repos}
  Existing fixture kinds: {existing_kinds}

  다음을 수행하라:
  1. /tmp/curator_sources/<repo>/ 로 shallow clone (`--depth 1`)
  2. 패턴 카탈로그(P1~P9) 각각 ripgrep 실행
  3. 매칭마다 함수 경계에서 ≤40줄 스니펫 추출
  4. repo당 최대 30 후보까지 수집
  5. `_workspace_curator/01_mining_candidates.json` 저장
  """,
  subagent_type: "general-purpose",
  model: "opus"
)
```

### Phase 2: 분류 (triager)

```
Agent(
  description: "idiom 후보 분류",
  prompt: """
  당신은 cpp-analyzer curator 파이프라인의 triager 에이전트입니다.

  `.claude/agents/triager.md`를 읽고 역할·원칙을 파악하라.
  `.claude/skills/cpp-analyzer-triage/SKILL.md`를 읽고 분류 방법론을 파악하라.
  `_workspace_curator/01_mining_candidates.json`과 `tests/fixtures/dataflow/expected.yaml`을 읽어라.

  각 후보를 DUP/NOISE/NOVEL로 분류하고, NOVEL 후보에는 novelty_score(1-5) + est_difficulty 부여.
  priority = novelty_score * difficulty_weight 기준으로 top 3를 추천.
  `_workspace_curator/02_triage_report.md`에 작성.
  """,
  subagent_type: "general-purpose",
  model: "opus"
)
```

### Phase 2.5: 승인 게이트 (필수)

1. `_workspace_curator/02_triage_report.md`의 top 3를 사용자에게 요약 제시
2. 사용자가 fixture화할 후보 ID를 명시할 때까지 대기
3. `--auto-add` 플래그 있으면 top-1 자동 진행

**승인 없이 Phase 3로 진행 금지.** fixture 추가는 프로젝트 repo를 수정하므로 반드시 사람 리뷰.

### Phase 3: fixture 작성 (fixture-writer)

```
Agent(
  description: "fixture 작성",
  prompt: """
  당신은 cpp-analyzer curator 파이프라인의 fixture-writer 에이전트입니다.

  `.claude/agents/fixture-writer.md`를 읽고 역할·원칙을 파악하라.
  `.claude/skills/cpp-analyzer-fixture/SKILL.md`를 읽고 작성 규약을 파악하라.
  `_workspace_curator/02_triage_report.md`와 승인된 후보 ID를 확인하라.

  승인된 후보: {approved_ids}

  라이선스-safe 재작성 체크리스트를 엄격히 지키며 다음을 수행:
  1. tests/fixtures/dataflow/{idiom_tag}.c 작성 (Cx prefix)
  2. expected.yaml에 새 섹션 + 엔트리 추가
  3. tests/test_dataflow.py에 TestC{N}{IdiomName} 클래스 추가
  4. `_workspace_curator/03_fixture_additions.md`에 요약 기록
  """,
  subagent_type: "general-purpose",
  model: "opus"
)
```

### Phase 4: 측정 & 프런티어 확인

benchmarker를 재호출하여 tests/test_dataflow.py 실행.

```
Agent(
  description: "curator 추가 후 벤치마크",
  prompt: """
  새로 추가된 fixture 포함 tests/test_dataflow.py를 실행하고
  `_workspace_curator/04_frontier_check.md`에 기록하라.

  신규 fixture가 FAIL이면 'Frontier Detected' 섹션에 명시.
  PASS면 '회귀 방호용 fixture 확보' 섹션에 명시.
  기존 fixture가 FAIL이면 **regression이며 critical** — 최상단에 경고.
  """,
  subagent_type: "general-purpose",
  model: "opus"
)
```

**판정:**
- 신규 FAIL + 기존 PASS: 정상 (프런티어 발견)
- 신규 PASS + 기존 PASS: 분석기가 이미 대응 중 — 회귀 방호 자산
- 기존 FAIL: **CRITICAL regression** — 롤백 권고

### Phase 5: 최종 보고 & 핸드오프

사용자에게:

```
## Curator 결과 — {date}

### 채굴
- 대상 repo: {repos}
- 후보: {N_candidates}

### 분류
- DUP: {n_dup}, NOISE: {n_noise}, NOVEL: {n_novel}
- 추천 top 3 승인: {approved}

### Fixture 추가
- 신규 .c: {files}
- expected.yaml 엔트리: {n_entries}

### 프런티어 상태
- FAIL (새 gap): {fail_list}
- PASS (방호 확보): {pass_list}

### 다음 단계 권장
- 다음 cycle에서 `cpp-analyzer-evolution` 실행 → reasoner가 위 FAIL 분석
- 자동 hand-off 없음 (사람 승인 필수)
```

## 데이터 흐름

```
사용자 → target repos
    ↓
[Phase 1: miner] → _workspace_curator/01_mining_candidates.json
    ↓
[Phase 2: triager] → _workspace_curator/02_triage_report.md
    ↓
[Phase 2.5: 승인 게이트] — 사용자 필수
    ↓
[Phase 3: fixture-writer] → tests/fixtures/dataflow/ 업데이트 + 03_fixture_additions.md
    ↓
[Phase 4: benchmarker 재사용] → _workspace_curator/04_frontier_check.md
    ↓
[Phase 5: 보고 — evolution 실행 권장]
```

## 에러 핸들링

| 상황 | 전략 |
|------|------|
| miner: clone 실패 | 해당 repo skip, 다른 repo 계속 |
| miner: 후보 0건 | triager 호출 생략, 사용자 보고 |
| triager: NOVEL 0건 | fixture-writer 생략, 사용자 보고 |
| 사용자 Phase 2.5에서 거절 | 전체 종료, 리포트만 보존 |
| fixture-writer: yaml 파싱 실패 | 해당 fixture rollback |
| Phase 4: 기존 테스트 regression | 최우선 경고, rollback 권고 |

## 제약 조건

- 외부 repo는 **읽기만** — commit/push 금지
- 프로젝트 repo의 변경은 Phase 3에서 새 파일 추가와 expected.yaml/test_dataflow.py 추가 섹션만
- 자동 커밋 금지 — 사람이 `git diff` 확인 후 수동 커밋
- 라이선스-safe 재작성 체크리스트 위반 시 즉시 rollback

## 트리거 키워드

- "fixture 채굴" / "curator 돌려줘" / "mine fixtures"
- "실 커널에서 패턴 가져와" / "새 프런티어 찾아줘"
- "벤치마크 fixture 확장"

## 테스트 시나리오

### 시나리오 A: 초기 실행
1. 사용자: "linux drivers/iio에서 idiom 채굴"
2. Phase 0: `_workspace_curator/` 생성, repo 확정
3. Phase 1-2: 후보 27건 → NOVEL 5건 → top 3 추천
4. Phase 2.5: 사용자 T1 승인
5. Phase 3: `linked_list_walk.c` + yaml + test 추가
6. Phase 4: 신규 FAIL, 기존 PASS
7. Phase 5: "Frontier Detected, evolution 실행 권장"

### 시나리오 B: NOVEL 0건
1. Phase 2에서 모두 DUP 또는 NOISE
2. Phase 3 생략
3. Phase 5: "이번 repo에서 새 idiom 없음, 다른 repo 제안"

### 시나리오 C: 기존 regression
1. Phase 4에서 기존 fixture FAIL
2. 최상단 경고 + Phase 3 변경 롤백 권고
