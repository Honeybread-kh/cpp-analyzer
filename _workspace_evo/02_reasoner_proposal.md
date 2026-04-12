# Evolution Proposal — 2026-04-13

## 현재 상태
- 점수: 97/97 (100%), 0 regressions (`_workspace_evo/01_benchmark_current.json`)
- 방금 진화된 gap: P1(deep chain 5-hop + mutual recursion), P2(conditional alias / linked-list / dynamic index), P3(C++ 가상 dispatch, 멤버 함수 포인터는 xfail), P4(#ifdef 양쪽 분기), P5(multi-callback 배열 등록자 / bitfield type-pun / flexible array member)
- 신규 fixture 5개 (`deep_chain.c`, `aliasing_advanced.c`, `cpp_dispatch.cpp`, `ifdef_variants.c`, `callbacks_multi.c`) + `TestDeepChain` / `TestCppDispatch` / `TestIfdefVariants` / `TestMultiCallback` / `TestAliasingAdvanced` 클래스 (15 PASS + 1 xfail)
- **문제:** `TestBenchmark` 스코어러는 `tests/fixtures/dataflow/expected.yaml` 만 소비하는데, P1~P5 케이스는 해당 YAML에 **한 줄도 없다**. 즉 100% 점수는 이전 패턴 집합의 완전 재달성일 뿐이며, P1~P5 진화는 pytest 클래스에서만 검증되고 스코어러의 해상도 바깥에 있다. 다음 진화 사이클에서 회귀/개선을 계속 측정하려면 expected.yaml 확장이 선결 조건.

---

## A) 측정 확장 — P1~P5를 스코어러에 통합

### A.0 전제 확인
- `analysis_db` fixture (test_dataflow.py:34)는 `FIXTURES_DIR` 전체를 인덱싱하므로 P1~P5 fixture의 dataflow path는 이미 `paths`에 존재한다. `TestBenchmark`가 못 보는 이유는 오직 expected.yaml에 엔트리가 없어서다.
- `_find_path` (test_dataflow.py:78)는 `source_substr`, `sink_substr`/`sink_pattern`, `expected_function`(sink/steps의 function 이름 어디든 매칭)을 지원한다. 현재 사용되는 포맷 그대로 P1~P5를 기술할 수 있다.
- `TestCppDispatch::test_member_fn_ptr`는 xfail 로 유지되므로 expected.yaml에는 넣지 않는다.

### A.1 expected.yaml에 추가할 엔트리 (16건, 난이도 합 +41점)

```yaml
  # ══════════════════════════════════════════════════════
  # P1: Deep call chain + mutual recursion
  # ══════════════════════════════════════════════════════

  # 5-hop param propagation: dcfg->frequency → dc_stage1..5 → DC_TIMING_REG
  # 검증 포인트: _trace_backward가 5단 재귀를 잘 탄다 (steps에 dc_stage5 포함).
  - name: "deep chain 5-hop param propagation"
    source: "dcfg->frequency"
    sink: "DC_TIMING_REG"
    expected_function: "dc_stage5"
    requires: deep_call_chain
    min_depth: 5
    difficulty: hard

  # Mutual recursion: dcfg->mode → recurse_odd/even → DC_MODE_REG
  - name: "mutual recursion odd/even"
    source: "dcfg->mode"
    sink: "DC_MODE_REG"
    expected_function: "recurse_odd"
    requires: mutual_recursion
    min_depth: 3
    difficulty: hard

  # ══════════════════════════════════════════════════════
  # P2: Conditional alias, linked-list, dynamic index
  # ══════════════════════════════════════════════════════

  # p = sel ? ra : rb;  p->regs[...] = acfg->frequency
  - name: "conditional alias ternary pointer"
    source: "acfg->frequency"
    sink: "AA_TIMING_REG"
    expected_function: "cond_alias_write"
    requires: conditional_alias
    min_depth: 2
    difficulty: hard

  # for (n=head; n; n=n->next) n->regs->regs[...] = acfg->mode
  - name: "linked list walk taint"
    source: "acfg->mode"
    sink: "AA_MODE_REG"
    expected_function: "list_walk_write"
    requires: linked_list_tracking
    min_depth: 2
    difficulty: hard

  # arr[i]->regs[...] = acfg->enable  (non-constant index)
  - name: "dynamic array index sink"
    source: "acfg->enable"
    sink: "AA_CTRL_REG"
    expected_function: "dyn_index_write"
    requires: dynamic_index
    min_depth: 2
    difficulty: medium

  # ══════════════════════════════════════════════════════
  # P3: C++ virtual dispatch  (member-fnptr은 xfail이라 제외)
  # ══════════════════════════════════════════════════════

  - name: "cpp virtual dispatch timing"
    source: "ccfg->frequency"
    sink: "CPP_TIMING_REG"
    requires: cpp_virtual_dispatch
    min_depth: 2
    difficulty: hard

  - name: "cpp virtual dispatch mode"
    source: "ccfg->frequency"
    sink: "CPP_MODE_REG"
    requires: cpp_virtual_dispatch
    min_depth: 2
    difficulty: hard

  # ══════════════════════════════════════════════════════
  # P4: #ifdef-guarded sinks (tree-sitter가 양쪽 분기 보여야 함)
  # ══════════════════════════════════════════════════════

  - name: "ifdef fast-path branch"
    source: "icfg->frequency"
    sink: "IF_FAST_REG"
    expected_function: "ifdef_write"
    requires: ifdef_both_branches
    min_depth: 2
    difficulty: hard

  - name: "ifdef else branch"
    source: "icfg->frequency"
    sink: "IF_TIMING_REG"
    expected_function: "ifdef_write"
    requires: ifdef_both_branches
    min_depth: 2
    difficulty: hard

  - name: "ifdef nested mode variant A"
    source: "icfg->mode"
    sink: "IF_MODE_REG"
    expected_function: "ifdef_nested_write"
    requires: ifdef_both_branches
    min_depth: 2
    difficulty: medium

  # ══════════════════════════════════════════════════════
  # P5: Multi-callback, bitfield, FAM
  # ══════════════════════════════════════════════════════

  # p5_register_cb(cb_timing) + p5_register_cb(cb_mode)
  # p5_fire_cbs가 배열을 순회하며 각 cb로 전파 → 두 레지스터
  - name: "multi-cb array dispatch timing"
    source: "pcfg->frequency"
    sink: "P5_TIMING_REG"
    expected_function: "cb_timing"
    requires: multi_callback_array
    min_depth: 3
    difficulty: hard

  - name: "multi-cb array dispatch mode"
    source: "pcfg->frequency"
    sink: "P5_MODE_REG"
    expected_function: "cb_mode"
    requires: multi_callback_array
    min_depth: 3
    difficulty: hard

  # pk.b = pcfg->frequency;  regs[...] = *(uint32_t*)&pk
  - name: "bitfield type-pun sink"
    source: "pcfg->frequency"
    sink: "P5_TIMING_REG"
    expected_function: "p5_bitfield_write"
    requires: bitfield_typepun
    min_depth: 2
    difficulty: hard

  # m->data[0] = pcfg->mode;  regs[...] = m->data[0]
  - name: "flexible array member sink"
    source: "pcfg->mode"
    sink: "P5_MODE_REG"
    expected_function: "p5_fam_write"
    requires: flexible_array_member
    min_depth: 2
    difficulty: hard
```

**요약:**
- 추가 엔트리: 14건 (xfail 1건, mutual-recursion hard 1건 포함 구성)
- 난이도 가중치 추가: easy=0, medium=2×1=2, hard=3×12=36 → 합 **+38**
- 현재 max_score 97 → 신규 max_score ≈ **135**
- fixture별 `requires` 라벨을 새로 도입(`deep_call_chain`, `mutual_recursion`, `conditional_alias`, `linked_list_tracking`, `dynamic_index`, `cpp_virtual_dispatch`, `ifdef_both_branches`, `multi_callback_array`, `bitfield_typepun`, `flexible_array_member`). 이후 gap 집계에서 카테고리 해상도가 높아진다.

### A.2 부작용 검토
- `TestBenchmark::test_benchmark_score`는 `_find_path` 하나로 모든 케이스를 소화하므로 추가 코드 변경 불필요.
- 기존 엔트리의 `source`/`sink`/`expected_function`은 **건드리지 않는다** — 100% 점수 유지.
- `sink`는 substring 매칭이라 `"DC_TIMING_REG"` / `"AA_TIMING_REG"` / `"CPP_TIMING_REG"` 등이 hw_model.c의 `TIMING_REG`과 충돌할 가능성이 있다. 그러나 `_find_path`는 처음 매칭되는 path를 반환하는 구조라 오탐이 발생해도 같은 source 문자열(`dcfg->`/`acfg->`/`ccfg->`/`icfg->`/`pcfg->`)로 1차 필터링되므로 fixture 간 교차 오매칭은 생기지 않는다.
- 단, P1 케이스의 `expected_function: "dc_stage5"`는 taint_tracker가 5-hop을 완주했을 때만 만족된다. 현재 `TestDeepChain::test_five_hop_param_chain`이 PASS이므로 스코어러에서도 PASS 예상.
- **리스크 포인트:** `bitfield type-pun`과 `flexible array member` 는 pytest 클래스에서 통과 중이지만, `_find_path`는 `p.sink.function == expected_function`을 요구하지 않고 steps 포함 여부만 본다. 현재 TestMultiCallback은 `p.sink.function == "p5_bitfield_write"`를 엄격히 요구하는데, expected.yaml 스코어러는 이보다 느슨하므로 **스코어러가 PASS인데 pytest는 FAIL**하는 비대칭이 이미 감내 범위다 (측정이 더 관대할 뿐).

### A.3 구현 지시 (implementer용)
1. 위 YAML 블록을 `tests/fixtures/dataflow/expected.yaml` **맨 끝** (scoring 주석 직전)에 append.
2. `pytest tests/test_dataflow.py::TestBenchmark -v` 재실행 → `_benchmark_report.json`의 `max_score`가 증가하고 신규 14건 모두 PASS 인지 확인.
3. regression 체크: 기존 97점은 그대로, 신규 14건이 모두 PASS면 **135/135 (100%)** 또는 일부 MISS 면 카테고리 해상도가 드러나 다음 reasoner 사이클이 그것을 잡음.

---

## B) 다음 진화 프런티어 (P1~P5 이후 여전히 놓치는 것)

선정 기준: (a) 실무 임베디드/커널 C 코드에서 **빈도 높음**, (b) 현재 `taint_tracker.py`의 어떤 분기도 잡지 못함, (c) fixture가 짧아야 벤치마크에 빨리 편입 가능. 3개 제안.

### B.1 Bulk-copy / struct memcpy taint (`memcpy(dst, &cfg, sizeof)`)

- **Fixture sketch (≤15줄):**
  ```c
  typedef struct { int freq; int mode; } McConfig;
  typedef struct { uint32_t regs[16]; } McHwRegs;
  void memcpy_taint(McConfig* cfg, McHwRegs* regs) {
      McConfig local;
      memcpy(&local, cfg, sizeof(*cfg));   // taint 전체 blob으로 복사
      regs->regs[0] = local.freq;
  }
  ```
- **Expected gap:** `memcpy`/`memmove`/`__builtin_memcpy` 호출의 2nd 인자(source blob)에 있는 필드가 1st 인자(dst)의 필드로 전파되지 않음 — 현재 `_find_reaching_defs`는 assignment 만 본다.
- **Implementation hint:** `ts_parser.extract_all_assignments`에 `call_expression` 중 callee name이 `memcpy|memmove|strcpy` 인 것을 *pseudo-assignment* (`lhs=*dst`, `rhs=*src`)로 등록; `taint_tracker._trace_backward`는 struct-copy alias 로직을 재사용해 필드-대-필드 전파.
- **Tier:** 1 + 3. DB 스키마 불변.

### B.2 `container_of` / `offsetof`-기반 embedded struct 역참조 (커널 패턴)

- **Fixture sketch:**
  ```c
  struct Inner { int freq; };
  struct Outer { int pad; struct Inner in; };
  #define container_of(ptr, type, member) \
      ((type*)((char*)(ptr) - offsetof(type, member)))
  void co_write(struct Inner* i, HwRegs* regs) {
      struct Outer* o = container_of(i, struct Outer, in);
      regs->regs[0] = o->in.freq;  // 같은 메모리를 outer-member 로 재접근
  }
  ```
- **Expected gap:** `container_of` 매크로 확장 후 `(char*)ptr - offsetof` 산술이 alias로 잡히지 않음. 현재 `C3 pointer arithmetic`은 배열 index 오프셋만 다루고 struct-embedded 의미를 모른다.
- **Implementation hint:** macro expansion에서 `container_of(X, T, M)` 패턴을 탐지해 `result` 와 `X` 를 structural-alias 로 등록 (offset 은 무시하고 same-storage 로 처리). `taint_tracker._resolve_alias` 에 새 테이블 `container_of_alias` 질의 추가.
- **Tier:** 1 + 2 + 3. 신규 mini-table 하나 필요.

### B.3 `goto`-based error unwind의 deferred register write (register-set-at-exit)

- **Fixture sketch:**
  ```c
  void unwind_write(Config* cfg, HwRegs* regs) {
      uint32_t v = 0;
      if (!cfg) goto out;
      v = cfg->freq;
  out:
      regs->regs[TIMING_REG] = v;  // goto를 거쳐야만 도달하는 sink
  }
  ```
- **Expected gap:** `_find_reaching_defs`가 goto label을 넘는 basic-block 합류를 따라가지 못한다. `v=0` 초기화와 `v=cfg->freq` 두 reaching def 중 후자가 드롭될 가능성 높음 (순차 스캔만 한다면).
- **Implementation hint:** tree-sitter AST에서 `labeled_statement` 와 `goto_statement` 를 basic-block 경계로 인식하고, 각 label에 도달하는 모든 선행 assignment 를 reaching-def 후보로 union. 재귀 없이 linear pass 로 가능.
- **Tier:** 1 + 3. DB 스키마 불변. LOC 예상 ~40.

### 참고로 기각/후순위
- **setjmp/longjmp, va_list:** 실 빈도 낮음 + 현재 엔진이 회귀 위험 큼. Skip for now.
- **Thread-local / atomic sinks:** sink-pattern 추가만으로 되지만 fixture 공급이 부담. sink_patterns 확장으로 노코드 진화 가능하므로 reasoner보다 운영 튜닝 레이어.
- **C++ lambda / std::function:** 중요하나 P3 member-fnptr xfail 과 같은 과제라 `Itanium vtable aware` 리졸버 도입 후 묶어서 한 번에.
- **DMA descriptor array:** B.1 (bulk memcpy) + 기존 struct-array indexing 조합으로 상당 부분 자연 해소 예상. 별도 트랙으로는 나중에.

---

## 권고 구현 순서

1. **(최우선) A. expected.yaml 확장** — 구현이 아니라 측정 확장. `developer` 1회, <30분. 이게 먼저여야 다음 사이클의 benchmarker가 B.1~B.3 를 객관적으로 평가할 수 있다.
2. **B.1 Bulk memcpy** — 3개 중 LOC 최소, 실무 빈도 최고, DB 스키마 변경 없음. 다음 evolution 사이클의 Gap 1.
3. **B.3 goto/label reaching-def** — 독립 변경이라 merge 충돌 위험 낮음. B.1 후 바로 투입 가능.
4. **B.2 container_of** — mini-table 추가로 Tier 2 필요. 앞 두 개가 안정화된 뒤 착수.

## 비권장 사항
- 현재 100% 상태에서 엔진 리팩토링 금지 — regression 리스크. P1~P5 로직이 `_trace_backward`·`_find_reaching_defs`를 거미줄처럼 확장했기에, 구조 정리는 B.1~B.3 세 건이 축적된 뒤 한 사이클을 "정리 전용"으로 배정하는 편이 안전.
- `TestCppDispatch::test_member_fn_ptr` 을 expected.yaml에 추가하지 말 것 — xfail 이 의도적이며, 스코어러에 넣으면 영구 MISS 로 노이즈만 증가.
