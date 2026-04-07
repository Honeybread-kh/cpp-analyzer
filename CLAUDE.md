# cpp-analyzer

C++ 정적 분석 도구. libclang + tree-sitter 기반 AST 파싱, 심볼 인덱싱, 호출 그래프, config 추적.
CLI (click) + MCP Server (FastMCP) 이중 인터페이스.

## 하네스: cpp-analyzer 개발

**목표:** cpp-analyzer의 기능 추가, 버그 수정, 리팩토링을 3단계 파이프라인(분석→구현→검증)으로 수행

**에이전트 팀:**
| 에이전트 | 역할 |
|---------|------|
| analyst | 코드베이스 탐색, 영향 범위 분석, 구현 방향 제안 (Explore) |
| developer | 전 계층 코드 구현 — DB, Analysis, CLI, MCP (general-purpose) |
| qa | 계층 간 경계면 교차 검증, 실행 테스트 (general-purpose) |

**스킬:**
| 스킬 | 용도 | 사용 에이전트 |
|------|------|-------------|
| cpp-analyzer-dev | 구현 패턴 가이드 (계층별 코드 패턴, CLI↔MCP 미러링 규칙) | developer |
| cpp-analyzer-qa | 경계면 검증 5종 + 실행 테스트 방법론 | qa |
| cpp-analyzer-orchestrator | 3단계 파이프라인 조율 (analyst→developer→qa) | 오케스트레이터 |

**실행 규칙:**
- 코드 변경 작업 (기능 추가, 버그 수정, 리팩토링 등) 요청 시 `cpp-analyzer-orchestrator` 스킬을 통해 에이전트 파이프라인으로 처리하라
- 단순 질문/확인/코드 리딩은 에이전트 없이 직접 응답해도 무방
- 모든 에이전트는 `model: "opus"` 사용
- 중간 산출물: `_workspace/` 디렉토리

**디렉토리 구조:**
```
.claude/
├── agents/
│   ├── analyst.md
│   ├── developer.md
│   └── qa.md
└── skills/
    ├── cpp-analyzer-dev/
    │   └── SKILL.md
    ├── cpp-analyzer-qa/
    │   └── SKILL.md
    └── cpp-analyzer-orchestrator/
        └── SKILL.md
```

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-04-06 | 초기 구성 | 전체 | 하네스 신규 구축 |
