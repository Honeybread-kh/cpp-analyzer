---
name: cpp-analyzer-orchestrator
description: "cpp-analyzer 개발 에이전트를 조율하는 오케스트레이터. 새 분석 기능 추가, CLI 커맨드 구현, MCP 도구 추가, 버그 수정, 리팩토링 등 코드 변경 작업 시 사용. 후속 작업: 수정, 보완, 다시 실행, 이전 결과 개선, 부분 재실행, 업데이트 요청 시에도 반드시 이 스킬을 사용. cpp-analyzer 기능 개발, 코드 수정, 분석 기능 확장, 파서 개선, DB 스키마 변경 요청 시 트리거."
---

# cpp-analyzer Development Orchestrator

cpp-analyzer 프로젝트의 개발 에이전트를 조율하여 코드 변경을 수행하는 통합 스킬.

## 실행 모드: 서브 에이전트

에이전트 간 통신보다 순차 파이프라인이 적합 (analyst 결과 → developer 구현 → qa 검증).

## 에이전트 구성

| 에이전트 | subagent_type | 역할 | 스킬 | 출력 |
|---------|--------------|------|------|------|
| analyst | Explore | 코드베이스 분석, 영향 범위 파악 | (내장) | `_workspace/01_analyst_report.md` |
| developer | general-purpose | 전 계층 코드 구현 | cpp-analyzer-dev | `_workspace/02_developer_changes.md` |
| qa | general-purpose | 경계면 검증, 실행 테스트 | cpp-analyzer-qa | `_workspace/03_qa_report.md` |

## 워크플로우

### Phase 0: 컨텍스트 확인

1. `_workspace/` 디렉토리 존재 여부 확인
2. 실행 모드 결정:
   - **`_workspace/` 미존재** → 초기 실행. Phase 1로 진행
   - **`_workspace/` 존재 + 사용자가 부분 수정 요청** → 부분 재실행. 해당 에이전트만 재호출
   - **`_workspace/` 존재 + 새 입력 제공** → 새 실행. 기존 `_workspace/`를 `_workspace_{YYYYMMDD_HHMMSS}/`로 이동

### Phase 1: 분석 (analyst)

사용자 요청을 analyst 에이전트에게 전달하여 코드베이스 분석을 수행한다.

```
Agent(
  description: "코드베이스 분석",
  prompt: """
  당신은 cpp-analyzer 프로젝트의 코드 분석 전문가입니다.
  
  `.claude/agents/analyst.md`를 읽고 역할과 원칙을 파악하라.
  
  사용자 요청: {user_request}
  
  다음을 분석하고 `_workspace/01_analyst_report.md`에 저장하라:
  1. 영향받는 파일과 변경 범위
  2. 기존 코드 패턴 (참고할 함수/클래스)
  3. 의존 관계
  4. 권장 구현 순서
  5. 주의할 엣지 케이스
  """,
  subagent_type: "Explore",
  model: "opus"
)
```

### Phase 2: 구현 (developer)

analyst의 분석 결과를 바탕으로 developer 에이전트가 코드를 구현한다.

```
Agent(
  description: "코드 구현",
  prompt: """
  당신은 cpp-analyzer 프로젝트의 개발 전문가입니다.
  
  `.claude/agents/developer.md`를 읽고 역할과 원칙을 파악하라.
  `.claude/skills/cpp-analyzer-dev/SKILL.md`를 읽고 구현 패턴을 파악하라.
  `_workspace/01_analyst_report.md`를 읽고 분석 결과를 확인하라.
  
  사용자 요청: {user_request}
  
  분석 결과에 따라 코드를 구현하라.
  변경 요약을 `_workspace/02_developer_changes.md`에 기록하라.
  """,
  subagent_type: "general-purpose",
  model: "opus"
)
```

### Phase 3: 검증 (qa)

developer의 구현 결과를 qa 에이전트가 검증한다.

```
Agent(
  description: "구현 검증",
  prompt: """
  당신은 cpp-analyzer 프로젝트의 QA 전문가입니다.
  
  `.claude/agents/qa.md`를 읽고 역할과 원칙을 파악하라.
  `.claude/skills/cpp-analyzer-qa/SKILL.md`를 읽고 검증 방법을 파악하라.
  `_workspace/02_developer_changes.md`를 읽고 변경 사항을 확인하라.
  
  경계면 검증 5종과 실행 테스트를 수행하라.
  결과를 `_workspace/03_qa_report.md`에 저장하라.
  """,
  subagent_type: "general-purpose",
  model: "opus"
)
```

### Phase 4: 결과 보고 및 수정 루프

1. `_workspace/03_qa_report.md`를 Read로 확인
2. FAIL 항목이 있으면:
   - 수정 범위가 작으면 (1~2개 파일) 직접 수정
   - 수정 범위가 크면 developer를 재호출하여 QA 피드백을 반영
   - 재호출 후 qa를 다시 실행 (최대 1회 루프)
3. 모든 항목이 PASS이면 사용자에게 결과 요약 보고

### Phase 5: 정리

1. `_workspace/` 보존 (삭제하지 않음)
2. 사용자에게 최종 결과 보고:
   - 변경된 파일 목록
   - 주요 변경 내용
   - QA 결과 요약

## 데이터 흐름

```
사용자 요청
    ↓
[analyst] → _workspace/01_analyst_report.md
    ↓
[developer] → 프로젝트 파일 수정 + _workspace/02_developer_changes.md
    ↓
[qa] → _workspace/03_qa_report.md
    ↓
FAIL? → [developer 재호출] → [qa 재호출] → 최종 보고
PASS? → 최종 보고
```

## 에러 핸들링

| 상황 | 전략 |
|------|------|
| analyst 실패 | 1회 재시도. 재실패 시 사용자에게 수동 분석 요청 |
| developer 실패 | 에러 로그 분석 후 1회 재시도 |
| qa FAIL 항목 존재 | developer 재호출 1회. 재실패 시 FAIL 항목 명시하고 사용자에게 보고 |
| 파이프라인 전체 실패 | 사용자에게 부분 결과와 함께 수동 개입 요청 |

## 테스트 시나리오

### 정상 흐름
1. 사용자: "search_symbols에 파일 경로 필터 옵션 추가해줘"
2. analyst: mcp_server.py, commands.py, repository.py 분석 → 보고서 생성
3. developer: repository.py에 file_filter 파라미터 추가 → CLI/MCP에 --file 옵션 추가
4. qa: V1(CLI↔MCP 미러링) PASS, V3(Analysis↔Repository) PASS, 실행 테스트 PASS
5. 최종 보고: 3개 파일 수정, 전 항목 PASS

### 에러 흐름
1. 사용자: "새 분석 기능 추가"
2. analyst → developer 정상 완료
3. qa: V1 FAIL — MCP 도구만 추가되고 CLI 커맨드 누락
4. developer 재호출 — CLI 커맨드 추가
5. qa 재호출 — 전 항목 PASS
6. 최종 보고: 재시도 1회 후 성공
