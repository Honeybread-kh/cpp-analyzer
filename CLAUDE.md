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

## 하네스: cpp-analyzer 진화 (evolution)

**목표:** 벤치마크(tests/test_dataflow.py) 점수를 기준으로 gap을 감지하고, 원인을 추론하여 개선을 제안·구현하는 자가 개선 파이프라인

**에이전트 팀:**
| 에이전트 | 역할 |
|---------|------|
| benchmarker | 벤치마크 실행, 카테고리별 집계, regression 감지 (general-purpose) |
| reasoner | gap 분석, 코드 수준(파일:함수) 원인 추론, 제안서 작성 (general-purpose) |
| developer (재사용) | 제안서에 따른 실제 구현 — 기존 개발 하네스의 developer 재사용 |

**스킬:**
| 스킬 | 용도 | 사용 에이전트 |
|------|------|-------------|
| cpp-analyzer-bench | 벤치마크 실행 파이프라인 + regression 감지 룰 | benchmarker |
| cpp-analyzer-reason | gap 카테고리별 추론 방법론 + 제안서 템플릿 | reasoner |
| cpp-analyzer-evolution | 전체 파이프라인 조율 (bench → reason → implement → re-bench) | 오케스트레이터 |

**실행 규칙:**
- 벤치마크 실행, gap 분석, 자동 진화, regression 체크 요청 시 `cpp-analyzer-evolution` 스킬을 사용하라
- 자동 구현(Phase 3)은 regression 없을 때만 실행, 한 번에 gap 1건
- PR 자동 머지 금지, 사람 리뷰 필수
- 모든 에이전트는 `model: "opus"` 사용
- 중간 산출물: `_workspace_evo/` 디렉토리 (개발 하네스의 `_workspace/`와 분리)
- implementer 단계는 기존 `cpp-analyzer-orchestrator` 스킬을 재귀 호출하여 수행

**디렉토리 구조:**
```
.claude/
├── agents/
│   ├── analyst.md         # 개발 하네스
│   ├── developer.md       # 개발 하네스 (evolution에서도 재사용)
│   ├── qa.md              # 개발 하네스
│   ├── benchmarker.md     # evolution 하네스
│   ├── reasoner.md        # evolution 하네스
│   ├── miner.md           # curator 하네스
│   ├── triager.md         # curator 하네스
│   └── fixture-writer.md  # curator 하네스
├── skills/
│   ├── cpp-analyzer-dev/           # 개발
│   │   └── SKILL.md
│   ├── cpp-analyzer-qa/            # 개발
│   │   └── SKILL.md
│   ├── cpp-analyzer-orchestrator/  # 개발 (오케스트레이터)
│   │   └── SKILL.md
│   ├── cpp-analyzer-bench/         # evolution
│   │   └── SKILL.md
│   ├── cpp-analyzer-reason/        # evolution
│   │   └── SKILL.md
│   ├── cpp-analyzer-evolution/     # evolution (오케스트레이터)
│   │   └── SKILL.md
│   ├── cpp-analyzer-mine/          # curator
│   │   └── SKILL.md
│   ├── cpp-analyzer-triage/        # curator
│   │   └── SKILL.md
│   ├── cpp-analyzer-fixture/       # curator
│   │   └── SKILL.md
│   └── cpp-analyzer-curator/       # curator (오케스트레이터)
│       └── SKILL.md
└── triggers/
    └── evolve-analyzer.md          # 주간 자동 실행 트리거
```

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-04-06 | 초기 구성 | 개발 하네스 전체 | 하네스 신규 구축 |
| 2026-04-11 | evolution 하네스 추가 | benchmarker, reasoner, cpp-analyzer-{bench,reason,evolution} | 벤치마크 기반 자가 개선 파이프라인 구축 (기존 개발 하네스와 분리) |
| 2026-04-13 | curator 하네스 추가 | miner, triager, fixture-writer, cpp-analyzer-{mine,triage,fixture,curator} | 외부 OSS에서 idiom 채굴 → fixture 편입으로 측정 범위 확장 (evolution과 직교, `_workspace_curator/` 격리) |

## 하네스: cpp-analyzer fixture 채굴 (curator)

**목표:** 실 OSS C/C++ 코드(Linux drivers, Zephyr 등)에서 taint/dataflow idiom을 채굴해 benchmark fixture로 편입. evolution이 "fixture 기준 점수"를 올리는 축이라면, curator는 "fixture의 대표성"을 넓히는 직교 축.

**에이전트 팀:**
| 에이전트 | 역할 |
|---------|------|
| miner | 외부 repo shallow clone + 휴리스틱 grep 기반 idiom 후보 채굴 (general-purpose) |
| triager | 기존 fixture 대조 → DUP/NOISE/NOVEL 분류 + novelty_score 부여 (general-purpose) |
| fixture-writer | 라이선스-safe 최소 재현 `.c` + expected.yaml + test class 작성 (general-purpose) |
| benchmarker (재사용) | 추가 후 프런티어 확인 (evolution 하네스에서 재활용) |

**스킬:**
| 스킬 | 용도 | 사용 에이전트 |
|------|------|-------------|
| cpp-analyzer-mine | 9종 휴리스틱 패턴 카탈로그 (container_of, fnptr table, goto unwind, IS_ERR, va_list, MMIO, bitfield, memcpy, linked-list) | miner |
| cpp-analyzer-triage | DUP/NOISE/NOVEL 분류 규칙 + novelty_score × difficulty 가중 | triager |
| cpp-analyzer-fixture | `Cx` prefix 규약, 라이선스-safe 재작성 체크리스트, yaml/test 템플릿 | fixture-writer |
| cpp-analyzer-curator | 전체 파이프라인 조율 (mine → triage → approval gate → write → bench) | 오케스트레이터 |

**실행 규칙:**
- "fixture 채굴", "curator 돌려줘", "실 커널에서 패턴 가져와" 등 요청 시 `cpp-analyzer-curator` 사용
- Phase 2.5 사용자 승인 게이트 필수 — Phase 3 fixture 추가는 프로젝트 repo를 수정하므로 사람 리뷰
- 외부 repo clone은 `/tmp/curator_sources/<repo>/` sandbox에만 — 프로젝트 repo 건드리지 않음
- 라이선스-safe 재작성 체크리스트 위반 시 즉시 rollback
- 신규 fixture가 FAIL이면 정상 (Frontier Detected → evolution 다음 cycle 입력)
- 기존 fixture regression은 CRITICAL — 최우선 롤백
- 모든 에이전트는 `model: "opus"` 사용
- 중간 산출물: `_workspace_curator/` (기존 두 하네스와 완전 분리)
- evolution으로 자동 hand-off 금지 (사람이 다음 cycle 트리거)
