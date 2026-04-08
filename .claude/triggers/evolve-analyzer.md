# cpp-analyzer Evolution Trigger

주간 자동 실행: cpp-analyzer의 분석 능력을 평가하고 개선 방향을 제안하는 추론 에이전트.

## 실행 순서

### 1단계: 벤치마크 실행 & 갭 감지

```bash
cd /Users/kwanghyunchoi/00_work/git_hb/mcp/cpp-analyzer
pytest tests/test_dataflow.py -v --tb=short
```

`_benchmark_report.json`을 읽고 현재 점수와 갭을 확인한다.

### 2단계: 갭 분석 & 추론

갭 리포트를 분석하여 다음을 추론하라:

1. **왜 이 패턴을 못 잡는가?** — taint_tracker.py의 _trace_backward 로직 한계 분석
2. **해결하려면 어떤 코드 변경이 필요한가?** — 구체적 함수/알고리즘 수준
3. **새로운 테스트 케이스가 필요한가?** — expected.yaml에 추가할 패턴
4. **새로운 분석 기능이 필요한가?** — 현재 아키텍처로 불가능한 것

### 3단계: 제안서 작성

분석 결과를 GitHub Issue로 생성하라:

```bash
gh issue create \
  --title "cpp-analyzer evolution: [요약]" \
  --body "## 벤치마크 점수\n...\n## 갭 분석\n...\n## 제안\n..." \
  --label "enhancement,auto-evolution"
```

### 4단계: (선택) 자동 구현

갭이 "requires: inter_procedural" 같은 특정 카테고리에 집중되면:
1. 해당 기능 개선을 위한 브랜치 생성
2. `cpp-analyzer-orchestrator` 스킬로 구현
3. PR 생성하여 리뷰 대기

## 제약 조건
- PR 자동 머지 금지 — 반드시 사람 리뷰 후 머지
- 벤치마크 점수가 하락하는 변경은 금지
- 새 테스트 케이스 추가는 자유롭게 허용
