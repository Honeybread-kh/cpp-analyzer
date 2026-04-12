# Evolution Proposal — 2026-04-13 (Coverage Expansion)

## 현재 상태
- 점수: 97/97 (100%), 0 regressions, 0 gaps
- 벤치마크 기준 추출 가능한 gap 소진 → **fixture 자체를 확장**하는 방향으로 전환
- 기존 커버 패턴: single-func taint, 2-hop inter-procedural, alias, union raw/parts, fnptr (local/struct/global), macro expansion, volatile MMIO, ptr arith, cast passthrough, struct-array cross-func, global relay, range clamp
- **미커버 영역**: 깊은 호출 체인(≥3 hop), 조건부 alias/phi, 링크드 리스트·컨테이너 순회, C++ 가상 디스패치, 비트필드/flexible array, 조건부 컴파일, 멀티 콜백 등록

전체 `hw_model.c`는 단일 파일/다소 평탄한 함수 구조이고, `multifile/`은 2-hop 수준만 포함. 실제 대규모 임베디드/커널 스타일 코드베이스에서 흔히 나타나는 다층/컨테이너 패턴이 체계적으로 비어있다.

---

## 제안 패턴 (우선순위 순)

### P1 — Deep call chain (4~6 hop) with mixed parameter/return propagation
- **Why it matters:** 실제 HAL/driver 코드는 `app_layer → service → hal → mmio_writer → reg_backend` 처럼 4~6단 호출이 일상. 현재 fixture는 최대 2-hop(`compute_divider → compute_timing`)이라 `_trace_backward`의 재귀 깊이/visited 처리가 실전 규모에서 동작하는지 검증되지 않는다. 100% 점수가 "scale 내성"을 의미하지 않는다.
- **Fixture sketch** (`deep_chain.c` + 헤더 하나):
  ```c
  // 5-hop: cfg->frequency → stage1 → stage2 → stage3 → stage4 → reg
  static uint32_t stage4(uint32_t v) { return v << 2; }
  static uint32_t stage3(uint32_t v) { return stage4(v) | 0x1; }
  static uint32_t stage2(uint32_t v) { return stage3(v / 2); }
  static uint32_t stage1(uint32_t v) { return stage2(v + 1); }
  void deep_chain_write(Config* cfg, HwRegs* regs) {
      regs->regs[TIMING_REG] = stage1(cfg->frequency);
  }
  // 추가: 상호 재귀 (even/odd 스타일) — taint depth 제한 검증용
  static uint32_t taint_even(uint32_t, int);
  static uint32_t taint_odd(uint32_t v, int n)  { return n==0 ? v : taint_even(v, n-1); }
  static uint32_t taint_even(uint32_t v, int n) { return n==0 ? v : taint_odd(v+1, n-1); }
  void mutual_recurse_write(Config* cfg, HwRegs* regs) {
      regs->regs[MODE_REG] = taint_odd(cfg->mode, 3);
  }
  ```
- **Expected gap:** `cpp_analyzer/analysis/taint_tracker.py::_trace_backward`와 `_find_callers_with_args`의 재귀 깊이 상한(현재 하드코딩 또는 visited set 기반으로 추정)이 4-hop 이상에서 조기 종료하거나 상호 재귀에서 무한 루프 방지 로직이 첫 hop에서 taint를 잃을 가능성. 특히 return-value chain은 각 callee를 다시 열어야 하므로 `_find_function_returns` (또는 대응 로직) 호출이 기하급수적으로 늘어난다.
- **Implementation hint:** 
  - `taint_tracker.py`의 재귀 깊이 파라미터(`max_depth`) 노출/튜닝
  - return-value 추적에서 callee 방문 캐시(memoization) 추가
  - 상호 재귀 대응을 위한 `(func, var)` 튜플 기반 visited set

---

### P2 — Conditional alias & linked-list / container traversal
- **Why it matters:** 커널/드라이버 코드의 전형: `p = cond ? &a : &b; p->field = tainted;` 그리고 `for (node = head; node; node = node->next) node->reg = cfg->x;`. 현재 alias 추적은 단일 대입(`r = hw`)만 커버. 조건부 alias와 반복자 기반 전파는 비어있다.
- **Fixture sketch:**
  ```c
  // (a) 조건부 alias
  void cond_alias_write(Config* cfg, HwRegs* ra, HwRegs* rb, int sel) {
      HwRegs* p = sel ? ra : rb;  // phi on pointer
      p->regs[TIMING_REG] = cfg->frequency;
  }
  // (b) 링크드 리스트 순회
  typedef struct Node { struct Node* next; HwRegs* regs; } Node;
  void list_walk_write(Config* cfg, Node* head) {
      for (Node* n = head; n; n = n->next) {
          n->regs->regs[MODE_REG] = cfg->mode;  // sink reachable via *any* node
      }
  }
  // (c) 가변 인덱스 struct array: arr[i]->field
  void dyn_index_write(Config* cfg, HwRegs** arr, int i) {
      arr[i]->regs[CTRL_REG] = cfg->enable;
  }
  ```
- **Expected gap:** 
  - (a) `taint_tracker.py::_resolve_alias` (또는 alias 맵 생성부, 아마 `ts_parser.py::extract_all_assignments` 내 pointer alias 판별)는 `conditional_expression`을 RHS로 받는 대입을 단일 target으로 단순화하지 못해 `p`의 alias 후보 집합을 `{ra, rb}` 대신 공집합 또는 하나만 선택할 것.
  - (b) 반복자 변수 `n`의 alias는 `head` / `n->next`이고, sink expr `n->regs->regs[...]`의 base가 고정되지 않는다. 현재 sink 매칭은 `regs->regs[...]` 문자열/AST 일치에 의존하므로 `n->regs->regs[...]`를 별도 패턴으로 취급해 놓칠 것.
  - (c) `arr[i]`의 `i`가 상수가 아닐 때 `struct_array_indexing` 로직(이미 `init_channels → array_struct_write`로 한 번 통과)이 인덱스를 요구 매칭하는지 확인 필요. 아마 상수 인덱스만 매칭한다.
- **Implementation hint:**
  - `ts_parser.py`의 alias 추출에 `conditional_expression` RHS 전개 추가 (양쪽 분기를 모두 alias 후보로 등록)
  - sink 인식기에 "base가 field chain인 경우" (`n->regs->regs[...]`) 재귀 하강 추가
  - 인덱스 wildcard 모드: `arr[*].field` 매칭 허용 옵션

---

### P3 — Virtual dispatch & member function pointer (C++)
- **Why it matters:** 프로젝트가 `cpp-analyzer`인데 fixture는 전부 C. `virtual` 메서드, ops-table 기반 디스패치는 C++/드라이버 코드의 핵심 패턴이고, 현재 함수 포인터 추적이 C 스타일 struct field fnptr까지만 커버. vtable/템플릿/멤버 함수 포인터는 전혀 없다.
- **Fixture sketch** (`cpp_dispatch.cpp` + `.h`):
  ```cpp
  struct Writer {
      virtual void write(HwRegs* r, uint32_t v) = 0;
  };
  struct TimingWriter : Writer {
      void write(HwRegs* r, uint32_t v) override { r->regs[TIMING_REG] = v; }
  };
  void vcall_write(Config* cfg, HwRegs* regs, Writer* w) {
      w->write(regs, cfg->frequency);   // virtual dispatch → TimingWriter::write
  }
  // 멤버 함수 포인터
  using MemFn = void (Writer::*)(HwRegs*, uint32_t);
  void memfn_write(Config* cfg, HwRegs* regs, Writer* w, MemFn fn) {
      (w->*fn)(regs, cfg->mode);
  }
  // 템플릿 instantiation
  template<typename T> void tmpl_write(T* w, HwRegs* r, uint32_t v) { w->write(r, v); }
  ```
- **Expected gap:** `taint_tracker.py` 및 `ts_parser.py`의 call-resolution은 libclang의 `CXXMethodDecl`/`is_virtual`을 활용하지 않는 것으로 보인다(현재 함수 포인터 추적 코드는 `_resolve_fnptr_target` 계열로 C 식별자 매칭 기반). `w->write(...)`는 기호 해석 시 추상 시그니처로 남아 callee 후보 집합을 만들지 못해 taint가 진입 함수에서 끊긴다. 멤버 함수 포인터 `(w->*fn)(...)`는 AST 노드 타입(`pointer_to_member_expression`)이 완전히 다른 경로라 추출 로직에 없을 가능성 높음.
- **Implementation hint:**
  - `ts_parser.py`에 C++ 모드 감지(`.cpp/.cc/.hpp`) + `field_expression` 기반 메서드 호출을 "class + method name"으로 정규화
  - 심볼 DB에 `class`/`override` 관계 (간단한 상속 그래프)를 추가하고, 가상 호출 시 모든 override 구현을 taint callee 후보로 확장
  - 멤버 함수 포인터는 별도 AST 매처 (`pointer_to_member_expression` in tree-sitter-cpp)

---

### P4 — Conditional compilation (#ifdef) branching sinks
- **Why it matters:** BSP/RTOS 코드는 동일 함수가 `#ifdef CONFIG_X`로 완전히 다른 레지스터에 쓴다. 벤치마크가 한 세트의 매크로 정의만 가정하면 "정의가 다른 빌드 타깃에서만 나타나는 sink"를 놓친다. 실제 취약점 추적에서 매우 흔한 누락 지점.
- **Fixture sketch:**
  ```c
  void ifdef_write(Config* cfg, HwRegs* regs) {
  #ifdef USE_FAST_PATH
      regs->regs[TIMING_REG] = cfg->frequency << 1;
  #else
      regs->regs[TIMING_REG] = cfg->frequency;
  #endif
  }
  // 헤더-only 정의 (static inline in .h)
  // hdr_only.h:
  //   static inline void hdr_write(HwRegs* r, uint32_t v) { r->regs[MODE_REG] = v; }
  ```
  expected.yaml 엔트리는 두 분기 모두 path로 인정(또는 `build_config: [A, B]` 두 variant로 테스트).
- **Expected gap:** libclang 파서가 단일 `-D` 정의로 한 분기만 AST에 포함. 다른 분기는 아예 파싱되지 않아 심볼화/taint 추적 대상이 되지 않는다. `cpp_analyzer/analysis/ts_parser.py` 또는 build-config 로더(`configs.csv` 관련 코드)에서 "두 분기 모두 별도로 파싱해 union 심볼 테이블을 만드는" 로직 부재로 추정.
- **Implementation hint:**
  - tree-sitter는 전처리기에 영향받지 않고 전 분기를 파싱 → `ts_parser.py` 주도로 `preproc_ifdef` 노드 양쪽 분기의 statement를 모두 수집하고, 각 sink에 "guarded by #ifdef X" 메타를 부착
  - libclang 경로는 다중 빌드 컨피그(`-D` 조합별) 재파싱 후 심볼 union

---

### P5 — Multi-registered callbacks & bitfield / flexible array sinks
- **Why it matters:** 콜백 등록이 한 번만 일어난다고 가정하는 것은 실제 이벤트 시스템에서 틀린다(`register_cb(A); ...; register_cb(B);`). 또한 비트필드(`struct { uint32_t x:4; }`)와 flexible array member(`struct { int n; uint32_t data[]; }`)는 임베디드/네트워크 스택의 표준 패턴인데 현재 fixture에 전무.
- **Fixture sketch:**
  ```c
  // (a) 멀티 콜백
  static cb_t g_cbs[4]; static int g_n;
  void register_cb(cb_t f) { g_cbs[g_n++] = f; }
  void fire_cbs(HwRegs* r, uint32_t v) { for (int i=0;i<g_n;i++) g_cbs[i](r, v); }
  static void cb_timing(HwRegs* r, uint32_t v) { r->regs[TIMING_REG] = v; }
  static void cb_mode(HwRegs* r, uint32_t v)   { r->regs[MODE_REG]   = v; }
  void multi_cb_init(void)                  { register_cb(cb_timing); register_cb(cb_mode); }
  void multi_cb_fire(Config* cfg, HwRegs* r){ fire_cbs(r, cfg->frequency); } // → both regs
  // (b) 비트필드
  typedef struct { uint32_t a:8, b:16, c:8; } Packed;
  void bitfield_member_write(Config* cfg, HwRegs* regs) {
      Packed p = {0}; p.b = cfg->frequency; regs->regs[TIMING_REG] = *(uint32_t*)&p;
  }
  // (c) flexible array
  typedef struct { int n; uint32_t data[]; } Msg;
  void fam_write(Config* cfg, Msg* m, HwRegs* regs) {
      m->data[0] = cfg->mode; regs->regs[MODE_REG] = m->data[0];
  }
  ```
- **Expected gap:**
  - (a) `taint_tracker.py`의 callback tracking(Gap A4로 추가된 `_resolve_global_fnptr_callees`류)는 **마지막** 등록값만 찾거나, 단일 대입만 추적 가능. 배열 인덱스로 누적 등록되는 패턴은 `g_cbs[g_n++] = ...` assignment의 LHS를 "배열 요소"로 단순화하지 못해 둘 다 callee 후보에 넣지 못한다.
  - (b) 비트필드는 `ts_parser.py::_parse_field_declaration`에서 `bitfield_clause` 노드를 무시하면 필드 타입/크기가 어긋나고, `*(uint32_t*)&p` 같은 type-punning sink 인식이 없어 taint가 끊긴다.
  - (c) flexible array `m->data[i]`는 `subscript_expression` 기반 alias 처리인데 현재 상수 인덱스 분기만 확인 필요.
- **Implementation hint:**
  - callback 추적에 "array-of-function-pointers" 전용 분기 추가: 배열 요소 LHS가 나올 때마다 callee 집합에 누적
  - `ts_parser.py`에 `bitfield_clause` 파싱 및 `field_identifier`의 비트 폭 메타 기록
  - type-punning (`*(T*)&x`)는 cast_tracking 연장선상에서 alias 선언 처리

---

## 우선순위 요약

| # | Pattern | 예상 영향 | 난이도 |
|---|---------|----------|--------|
| P1 | Deep chain (4~6 hop) + 상호 재귀 | taint_tracker 재귀·캐싱 강건성 확보 | 중 |
| P2 | 조건부 alias / 리스트 순회 / dynamic index | alias 모델 현실화 | 중~상 |
| P3 | C++ 가상 디스패치 / 템플릿 / 멤버 fnptr | 프로젝트 이름값(C++) 회복 | 상 |
| P4 | #ifdef 분기 sink + 헤더-only 정의 | 빌드 컨피그 내성 | 상 |
| P5 | 멀티 콜백 / 비트필드 / flexible array | 커버리지 다양성 | 중 |

**구현 권고 순서:** P1 → P2 → P5 → P4 → P3
(P3 C++는 파서 레이어 확장 비용이 커서 후순위, P1/P2는 기존 taint 엔진 튜닝으로 ROI가 높음)

## 신규 fixture 배치 제안

현재 `hw_model.c` 하나가 비대(375줄)하므로 기능 그룹별 분리 권장:
```
tests/fixtures/dataflow/
├── hw_model.c              # 기존 유지 (레거시)
├── deep_chain.c            # P1
├── aliasing_advanced.c     # P2
├── cpp_dispatch.cpp        # P3 (새로 C++)
├── ifdef_variants.c        # P4
├── callbacks_multi.c       # P5
└── expected.yaml           # 새 섹션으로 그룹 추가
```

## 비권장 사항

- `hw_model.c`에 P1~P5를 전부 밀어넣는 것 — 이미 포화 상태. 파일 분할 동반 필수.
- Scale (100+ 파일) 테스트를 벤치마크에 포함 — 벤치 실행 시간 폭증. 별도 `tests/scale/`로 분리하는 편이 낫다.
- C++ 패턴(P3)을 tree-sitter만으로 해결 시도 — 가상 디스패치 resolution은 최소한의 클래스 상속 그래프(libclang의 `get_children` / `CXCursor_CXXBaseSpecifier` 활용)가 필요.
