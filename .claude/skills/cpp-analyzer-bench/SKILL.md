---
name: cpp-analyzer-bench
description: "cpp-analyzer 벤치마크 실행 및 regression 감지 스킬. tests/test_dataflow.py를 실행하고 _benchmark_report.json을 분석하여 difficulty/requires 카테고리별 합격률을 집계하며, 이전 측정 대비 점수 하락(regression)을 감지한다. benchmarker 에이전트가 사용. 벤치마크 실행, 점수 측정, 성능 측정, 회귀 감지, 진화 파이프라인의 측정 단계에서 트리거."
---

# cpp-analyzer Benchmark Skill

벤치마크를 결정적으로 실행하고, 회귀 감지까지 수행하기 위한 실행 가이드.

## 왜 이 스킬이 필요한가

하네스의 진화(Phase 7)는 "객관적 측정"에서 시작한다. LLM의 주관적 판단이 아니라 **숫자**로 변화를 증명해야 점수 하락을 차단할 수 있다. 이 스킬은 측정의 일관성과 gap 리포트 구조를 강제한다.

## 측정 파이프라인

### Step 1: 작업 디렉토리 준비

```bash
cd /Users/kwanghyunchoi/00_work/git_hb/mcp/cpp-analyzer
mkdir -p _workspace_evo
```

이전 측정 결과가 `_workspace_evo/01_benchmark_current.json`에 있으면, 비교 기준점으로 `01_benchmark_before.json`으로 승격시킨다:

```bash
[ -f _workspace_evo/01_benchmark_current.json ] && \
  mv _workspace_evo/01_benchmark_current.json _workspace_evo/01_benchmark_before.json
```

### Step 2: 벤치마크 실행

```bash
uv run pytest tests/test_dataflow.py -v --tb=short 2>&1 | tee _workspace_evo/01_benchmark_pytest.log
```

실패한 테스트가 있어도 계속 진행한다 — XFAIL은 정상, 실제 FAIL이면 리포트에 명시.

### Step 3: 리포트 파싱 및 집계

`tests/test_dataflow.py`는 실행 후 프로젝트 루트에 `_benchmark_report.json`을 쓴다. 이를 `_workspace_evo/`로 옮기며 추가 집계를 덧붙인다.

파이썬 스니펫 (bash heredoc로 실행):

```python
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import subprocess

root = Path("/Users/kwanghyunchoi/00_work/git_hb/mcp/cpp-analyzer")
raw = json.loads((root / "_benchmark_report.json").read_text())

by_diff = defaultdict(lambda: {"pass": 0, "total": 0})
by_req = defaultdict(lambda: {"pass": 0, "total": 0})
for r in raw["results"]:
    d, q = r["difficulty"], r["requires"]
    by_diff[d]["total"] += 1
    by_req[q]["total"] += 1
    if r["status"] == "PASS":
        by_diff[d]["pass"] += 1
        by_req[q]["pass"] += 1

raw["timestamp"] = datetime.utcnow().isoformat() + "Z"
raw["commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
raw["branch"] = subprocess.check_output(["git", "branch", "--show-current"], cwd=root).decode().strip()
raw["by_difficulty"] = dict(by_diff)
raw["by_requires"] = dict(by_req)

(root / "_workspace_evo/01_benchmark_current.json").write_text(json.dumps(raw, indent=2))
```

### Step 4: Regression 감지

이전 `01_benchmark_before.json`이 존재하면 diff를 계산한다.

**Regression 기준:**
- 전체 점수 감소 (`pct` 하락)
- 이전엔 PASS였는데 지금 MISS인 항목이 **1개라도** 존재
- 이전엔 존재하던 테스트 케이스가 사라짐

regression이 있으면 리포트 최상단에 반드시 `⚠ REGRESSION DETECTED` 표시. 이 플래그는 파이프라인의 implementer 단계를 차단하는 신호로 사용된다 (evolution-orchestrator가 확인).

### Step 5: 사람용 요약 작성

`_workspace_evo/01_benchmark_report.md`에 다음 구조로 작성:

```markdown
# Benchmark Report — {timestamp}

**Commit:** {sha} ({branch})
**Score:** 15/21 (71.4%)  {↑/↓/= vs previous}

{REGRESSION DETECTED (있을 경우)}

## Delta (이전 대비)
| 항목 | 이전 | 현재 | 변화 |
|------|------|------|------|
| 점수 | 14 | 15 | +1 |
| ... | | | |

## 카테고리별 합격률
### Difficulty
- easy: 5/5 (100%)
- medium: 4/5 (80%)
- hard: 0/2 (0%)

### Requires
- basic: 5/5
- inter_procedural: 0/2  ← 주 gap
- ...

## Gap 리스트
1. multi-hop: config → divider → timing → reg (hard, inter_procedural)
2. two-layer: config → fw → hw register (hard, inter_procedural)
```

## 품질 기준

- **결정적 실행**: 같은 commit에서 두 번 실행하면 같은 점수가 나와야 한다. 무작위성이 발견되면 벤치마크 결함으로 보고
- **필수 필드**: `score`, `pct`, `results`, `gaps`, `by_difficulty`, `by_requires`가 모두 존재해야 reasoner가 사용 가능
- **리포트 간결성**: 사람용 요약은 한 화면(~50줄) 이내

## 반복 패턴 주의

이 스킬의 스크립트(Step 3)는 매 실행마다 동일하다. 향후 `scripts/aggregate.py`로 번들링하는 것을 고려. (현재는 인라인 유지 — 로직이 짧고 바뀔 수 있음)
