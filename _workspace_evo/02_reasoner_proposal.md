# Evolution Proposal — 2026-04-13 (Frontier Round)

## 현재 상태
- 점수: **153/153 (100%)**, 0 gap, 0 regression (`_workspace_evo/01_benchmark_current.json`)
- by_requires: 39개 카테고리 전부 100%, 난이도별(easy/medium/hard) 모두 100%
- 유일한 XFAIL: `test_member_fn_ptr` (C++ pmf, 의도적 유지)
- 직전 사이클: **A (expected.yaml +14) + B.1 memcpy + B.2 container_of + B.3 goto unwind** 모두 PASS
- **이번 사이클 미션:** 스코어러 해상도 바깥에 있는 "아직 fixture가 없는" 실무 C/C++ 패턴을 새 프런티어로 승격

## 프런티어 선정 기준
1. 실무 임베디드/커널/드라이버 코드에서 **빈도 높음**
2. 현재 `taint_tracker.py`의 어떤 분기도 잡지 못함 (기존 규칙의 trivial 확장이 아니어야 함)
3. Fixture가 짧게 쓰여도 의미가 드러남 (≤40 LOC fixture)
4. 이전 제안서(`_workspace_evo_20260413_091509/02_reasoner_proposal.md`)의 B.1~B.3 및 기각/후순위와 중복 금지
   - 기각 항목(setjmp/longjmp, va_list, C++ lambda/std::function, DMA descriptor array)은 "왜 기각됐는가"를 재검토하여 **완화된 부분집합**만 채택

---

## Frontier F1 — `writel()` / `iowrite32()` 등 커널 MMIO accessor의 2-argument sink

### 패턴 실물 (스케치)
```c
// Linux 스타일 MMIO accessor. 2번째 인자가 sink(주소), 1번째 인자가 값.
static inline void writel(u32 val, volatile void __iomem *addr) { *(volatile u32*)addr = val; }

struct f1_cfg { u32 freq; u32 mode; };
struct f1_regs { void __iomem *base; };

void f1_program(struct f1_cfg *cfg, struct f1_regs *r) {
    writel(cfg->freq, r->base + F1_TIMING_OFF);   // sink = r->base + offset
    iowrite32(cfg->mode, r->base + F1_MODE_OFF);  // callee 이름만 다름
}
```

### 왜 현재 놓치는가 (원인 가설)
- **현상:** 현재 sink 인식은 `regs->regs[IDX] = val` 형태의 assignment 또는 `REG_WRITE(...)` 매크로 확장에 집중. `writel(val, addr)` 같은 **함수 호출형 sink** 는 callee가 "레지스터에 쓴다"는 의미를 엔진이 모름.
- **실패 지점:** `taint_tracker.trace`의 sink discovery 루프는 `assignment_expression` / known macro 만 주사. `call_expression` 중 callee 이름이 MMIO accessor 화이트리스트에 속하는 케이스 미처리.
- **근거:** 기존 `volatile_mmio` 카테고리는 `*(volatile u32*)addr = val` 형태의 직접 역참조만 본다. 커널/드라이버에서는 직접 역참조보다 `writel`/`iowrite32`/`__raw_writel`/`regmap_write` 호출이 절대 다수.

### 구현 힌트
- **Tier 1 (파서):** `ts_parser.extract_all_assignments` 에 `call_expression` 중 callee ∈ `{writel, writel_relaxed, iowrite8/16/32/64, __raw_writel, regmap_write, regmap_update_bits}` 을 만나면 pseudo-assignment 로 기록: `lhs = <2nd arg text as sink>` (또는 `regmap_*`의 경우 1st arg=regmap, 2nd=reg, 3rd=val), `rhs = <val arg>`
- **Tier 3 (트래커):** sink_patterns 확장만으로 `regmap_write(dev, REG_X, cfg->freq)` 의 `REG_X` 식별 가능. writel 계열은 "주소식 substring(예: `BASE + OFF`)" 자체를 sink 문자열로 저장.
- **스코어러 통합:** `_find_path` 가 substring 매칭이므로 sink 에 `writel` 또는 `F1_TIMING_OFF` 문자열이 들어가면 자연 매칭.

### LOC 추정
- 파서 화이트리스트 + pseudo-assignment 등록: ~35 LOC
- 신규 fixture (`mmio_accessor.c`): ~40 LOC
- `expected.yaml` 엔트리: 3건 (writel timing / iowrite32 mode / regmap_write)

### 난이도
**중**. DB 스키마 불변. B.1 memcpy 가 이미 "pseudo-assignment via call" 메커니즘을 깔아놨으므로 그 위에 callee 화이트리스트만 추가.

---

## Frontier F2 — 구조체 **부분** 초기화 / designated initializer 를 통한 taint 주입

### 패턴 실물 (스케치)
```c
typedef struct { u32 freq; u32 mode; u32 flags; } F2Cfg;
typedef struct { u32 regs[8]; } F2Regs;

// 케이스 A: 호출자 사이트에서 compound literal 로 필드 지정 초기화
void f2_apply(F2Cfg c, F2Regs *r) {
    r->regs[0] = c.freq;
    r->regs[1] = c.mode;
}

void f2_entry(u32 user_freq, F2Regs *r) {
    f2_apply((F2Cfg){ .freq = user_freq, .mode = 0x3 }, r);
    //        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ 익명 compound literal
}

// 케이스 B: 정적 초기화 + 배열/구조체 중첩 designated init
static const F2Cfg f2_profiles[] = {
    [0] = { .freq = 100, .mode = 1 },
    [1] = { .freq = USER_FREQ,        // 매크로 source
            .mode = 2,
            .flags = F2_DEF },
};
void f2_select(int i, F2Regs *r) { f2_apply(f2_profiles[i], r); }
```

### 왜 현재 놓치는가
- **현상:** `user_freq` 가 compound literal 의 `.freq` 필드로 주입된 뒤 함수 인자로 by-value 전달되어 `c.freq` 로 소비되는 흐름을 `_trace_backward`가 끊는다.
- **실패 지점:** 현재 struct-field 전파는 "`x.field = y` assignment" 와 "`struct_array[k].field`" 에 의존. **C99 designated initializer** (`initializer_list` / `initializer_pair` AST 노드) 는 extractor 가 필드별 할당으로 변환하지 않는다.
- **배경:** 드라이버/플랫폼 코드에서 platform_data, of_device_id, clk_ops 같은 큰 정적 테이블이 전부 designated init 으로 기술된다. taint 의 "숨은 source" 가 여기서 시작한다.

### 구현 힌트
- **Tier 1 (파서):** `initializer_list` 노드 방문 시 각 `initializer_pair` 를 synthetic assignment 로 등록:
  - `(F2Cfg){ .freq = X }` → 임시 변수 `__tmp_N` 을 도입해 `__tmp_N.freq = X` 등록, 함수 인자 사이트에서는 `<formal_param>.freq = X` 로 직접 바인딩.
  - 정적 테이블은 `f2_profiles[k].freq = X` 형식으로 (struct_array_indexing 로직 재사용 가능).
- **Tier 3 (트래커):** compound literal 을 인자로 받는 call 은 "인자별 필드 바인딩"을 aliased param으로 처리. `_find_callers_with_args` 가 각 `initializer_pair` 를 읽도록.
- **회귀 주의:** `_trace_backward` 의 초기화 vs 할당 우선순위 — `int x = cfg->freq;` 는 이미 declarator init 으로 잡고 있음. 중복 등록 금지 위해 "initializer_list 내부" 에서만 합성.

### LOC 추정
- 파서 확장: ~60 LOC (AST 방문 + 합성 할당 등록)
- fixture `designated_init.c`: ~35 LOC
- `expected.yaml`: 3건 (compound literal call-site / static profile table / nested init)

### 난이도
**상**. 파서 깊은 변경 + 합성 변수 도입으로 다른 assignment 집계에 오염 위험 → visited set / source-location 키로 격리해야 함. 회귀 리스크를 고려해 별도 PR 로 분리 권장.

---

## Frontier F3 — 함수 포인터 **테이블** + **enum 인덱스** dispatch (ops table)

### 패턴 실물 (스케치)
```c
typedef struct f3_cfg { u32 freq; u32 mode; } F3Cfg;
typedef struct f3_regs { u32 regs[8]; } F3Regs;

enum f3_op { F3_OP_TIMING, F3_OP_MODE, F3_OP_CTRL, F3_OP_MAX };

typedef void (*f3_fn)(F3Cfg*, F3Regs*);
static void f3_do_timing(F3Cfg *c, F3Regs *r) { r->regs[0] = c->freq; }
static void f3_do_mode  (F3Cfg *c, F3Regs *r) { r->regs[1] = c->mode; }
static void f3_do_ctrl  (F3Cfg *c, F3Regs *r) { r->regs[2] = c->freq | c->mode; }

// designated init 가 겹치는 현실 케이스 — F2 와 결합 시 난이도 상승
static const f3_fn f3_ops[F3_OP_MAX] = {
    [F3_OP_TIMING] = f3_do_timing,
    [F3_OP_MODE  ] = f3_do_mode,
    [F3_OP_CTRL  ] = f3_do_ctrl,
};

void f3_dispatch(enum f3_op op, F3Cfg *c, F3Regs *r) {
    f3_ops[op](c, r);          // enum index → 정확한 callee 해석
}
```

### 왜 현재 놓치는가
- **현상:** `multi_callback_array` 카테고리는 배열에 **동적으로 register/fire** 하는 패턴을 푼다. 그러나 enum index 를 직접 쓰는 static ops table 은 "index → specific callee" 매핑을 풀어야 하며, 지금은 "배열의 모든 원소로 union taint" 근사로 해결 중이다 (보수적 over-taint).
- **실패 지점:** `fnptr_tracking` + `struct_array_indexing` 는 각각 단일 filed/array access 를 해석하지만 **enum 상수 index** 로 선택된 함수 포인터는 해석 대상 아님. 현재 테스트가 통과하는 건 `union of callees` 덕분이라 **세분화된 질의(예: "F3_OP_MODE 경로만")** 시 false positive 로 드러난다.
- **근거:** `taint_tracker._resolve_fnptr` (또는 유사 로직) 은 배열 base + dynamic index 는 fan-out 하지만, enum 상수 index 를 constant-fold 해 단일 callee 로 좁히지 않는다.

### 구현 힌트
- **Tier 1 (파서):** 정적 `initializer_list` + designated index (`[CONST] = fn`) 를 `fnptr_table` 로 등록 (`table_name, index_value, callee_name`). Enum 값은 기존 enum resolver 로 정수화.
- **Tier 2 (DB):** 신규 mini-table `fnptr_indexed_table(table_name TEXT, index_value INTEGER, callee TEXT)`. ~1 마이그레이션.
- **Tier 3 (트래커):** `subscript_expression` callee 해석 시 `base` 가 `fnptr_indexed_table` 의 `table_name` 이고 `index` 가 enum 상수 또는 constant expression 으로 접히면 정확한 callee 로 디스패치. 접히지 않으면 기존 fan-out 유지 (후방 호환).
- **관찰:** F2 (designated init) 와 같은 파서 확장을 공유한다. F2 를 먼저 머지하면 F3 의 Tier 1 비용이 절반으로 줄어든다.

### LOC 추정
- 파서 + DB 마이그레이션: ~50 LOC
- 트래커 분기: ~30 LOC
- fixture `fnptr_indexed_table.c`: ~45 LOC
- expected.yaml: 3건 (F3_OP_TIMING 전용 / F3_OP_MODE 전용 / 기본 동적 index fan-out)

### 난이도
**상**. DB 스키마 변경 + constant folding 책임. 단 F2 구현 자산을 재사용할 수 있어 **F2 다음에 F3** 순서면 체감 비용은 중.

---

## 신규 테스트 케이스 제안 (expected.yaml 증분)
- `mmio_accessor: writel`, `iowrite32`, `regmap_write` — 3건 (F1)
- `designated_init: compound-literal arg`, `static profile table`, `nested init` — 3건 (F2)
- `fnptr_indexed_table: F3_OP_TIMING`, `F3_OP_MODE`, `dynamic op` — 3건 (F3)
- 총 **+9 테스트**, 난이도 합 예상 +20~24 점 (medium/hard 혼합)

## 우선순위
1. **(최우선) F1 — MMIO accessor sink**: 구현 비용 최저, 실무 커버리지 최고(리눅스 드라이버 전반). B.1/B.2 에서 쌓은 pseudo-assignment 메커니즘 재사용. **다음 사이클 Gap 1 로 적합**.
2. **F2 — designated initializer 합성 assignment**: 임팩트 큼(platform_data 전체 커버), 회귀 리스크 중간. F1 안정화 후 독립 PR.
3. **F3 — enum-indexed fnptr ops table**: F2 의 designated-init 파싱 재사용이 이득. F2 머지 직후 착수.

## 비권장 / 후순위 (재검토)
- **setjmp/longjmp**: 여전히 후순위 — 실 빈도 낮고 엔진에 jump-table 이 필요해 ROI 낮음.
- **va_list / `printk(...)` 포맷 taint**: 디버그 경로 위주라 보안/정합성 영향 낮음. skip.
- **C++ lambda / std::function**: P3 member-fnptr xfail 과 동반 해결 대상. **별도 C++ 전용 사이클**로 묶음.
- **DMA descriptor array**: B.1 (memcpy) + struct_array_indexing 이 이미 상당 부분 커버. 독립 프런티어로는 보류.
- **100% 상태에서 엔진 리팩토링 금지** — regression 리스크 > 리턴.

## 회귀 방지 체크리스트 (implementer 전달용)
- [ ] 파서 확장 시 기존 `extract_all_assignments` 결과 count 가 감소하지 않는지 카운트 회귀 테스트
- [ ] F2 합성 변수(`__tmp_N`)는 단일 파일/단일 노드 scope 에서만 유효 — 전역 오염 금지
- [ ] F3 DB 마이그레이션은 `IF NOT EXISTS` 로 멱등화, 기존 인덱스 DB 재사용 가능해야 함
- [ ] 각 프런티어는 독립 PR — F1/F2/F3 한 번에 묶지 않는다 (bisection 용이성)
