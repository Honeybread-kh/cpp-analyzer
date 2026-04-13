# Reasoner Proposal — 2026-04-13 (post 100% saturation)

현재 벤치마크 171/171 (100%). 신규 프런티어 3건을 제안한다.
이전 기각 항목(setjmp/va_list/lambda/DMA descriptor)은 **완화된 부분집합**으로 재검토했다.

---

## Frontier G1 — `callback_t cb = cfg->fn; cb(arg)` : indirect call via local fnptr variable

### 패턴 스케치
```c
struct driver_ops { int (*probe)(struct dev*, u32 cfg); };

static int dispatch(struct dev *d, const struct driver_ops *ops, u32 cfg) {
    int (*fp)(struct dev*, u32) = ops->probe;   // copy fnptr to local
    if (!fp) return -ENODEV;
    return fp(d, cfg);                           // <-- indirect call site
}
```
`ops->probe` 는 F3 덕분에 테이블 엔트리로 resolve 되지만, 한 번 **로컬 변수에 대입된 뒤 호출**되면 놓친다. 실무 드라이버에서 "null check → 호출" 이디엄으로 빈번.

### 왜 현재 놓치는가
- `taint_tracker.py:_scan_sinks` 및 call-graph 해석 경로는 `ops->probe(...)` 와 같이 **직접 멤버 호출 구문**만 fnptr-table 조회와 연결한다 (F3: `_load_all_files` → `populate fnptr table` → 멤버 접근 callee).
- 로컬 변수 `fp` 에 대한 **fnptr alias propagation** 이 없음. `_build_alias_map` 은 pointer alias (container_of, `a = b`)만 다루고, "lhs가 함수 포인터이면 callee set도 복사" 하는 분기가 없다.
- `ts_parser.py` 의 assignment 수집은 rhs 가 `ops->probe` 인 경우를 일반 field-read 로 flatten 할 뿐, fnptr-kind tag 를 붙이지 않는다.

### 구현 힌트
- **ts_parser**: assignment 추출 시 rhs 가 `field_expression` 이고 declared type이 function pointer 이면 `rhs_kind="fnptr_alias"` 메타 추가.
- **taint_tracker**:
  - `AliasMap` 에 `fnptr_alias: dict[str, str]` 추가 (local var → canonical `Type.member`).
  - `_scan_sinks` 에서 `call_expression` 의 callee 가 식별자 하나뿐이면 alias map 조회 후 F3 테이블로 재라우팅.
- **call_graph.py**: 동일 변환을 edge 생성 루프에 미러링 (edge kind=`indirect_via_local`).

**LOC**: ~80 / **난이도**: med
**우선순위**: ★★★ (1순위 — 실무 hit-rate 높음, 기존 F3 인프라 재사용)

---

## Frontier G2 — `errno`/`IS_ERR(ptr)` 반환 convention 경유 taint

### 패턴 스케치
```c
struct regmap *rm = devm_regmap_init(dev, cfg);   // source
if (IS_ERR(rm)) return PTR_ERR(rm);
regmap_write(rm, REG_CTRL, user_val);              // sink on non-error branch
```
또는:
```c
ret = of_property_read_u32(np, "cfg", &val);       // val tainted iff ret==0
if (ret) return ret;
writel(val, base + OFFSET);                        // sink
```

### 왜 현재 놓치는가
- `of_property_read_u32` 같은 **out-parameter + return-code** 패턴은 source 로 등록되어 있으나, `IS_ERR/PTR_ERR` 가드 뒤에서 사용되는 포인터-형 source (`devm_regmap_init`, `ioremap`) 는 **return 값 자체가 sink 의 첫 인자(handle)**가 되는 경우가 많다.
- `taint_tracker._trace_backward` 는 sink arg 의 reaching def 을 찾을 때 `IS_ERR(x)` 를 branch guard 로 인식하지 않음 — 그냥 통과. 즉 guard-correlation 정보가 없어 **false confidence** 는 피하지만, Linux 스타일 "error-coded pointer" source 가 `DEFAULT_SOURCE_PATTERNS` 에 빠져 있어 애초에 taint 시작도 안 함.
- `path_tracer.py` 의 경로 리포트에도 `IS_ERR` 가드 노드가 없다.

### 구현 힌트
- **taint_tracker.DEFAULT_SOURCE_PATTERNS**: `devm_regmap_init`, `devm_ioremap`, `ioremap`, `of_iomap`, `clk_get`, `pinctrl_get` 등을 **pointer-returning source** 로 추가.
- `_trace_backward` 에 `IS_ERR`/`PTR_ERR` 인식 분기: reaching def 직후 `if (IS_ERR(x)) return ...;` 이 있으면 그 뒤 use 를 "guarded_use" 로 태그 (path confidence 유지).
- `ts_parser`: branch-guard 수집에 `IS_ERR` 호출 패턴 추가 — 이미 존재하는 predicate guard 로직 재사용.

**기각 재검토 노트**: setjmp/longjmp 전면 지원은 여전히 복잡도 대비 hit 낮아 기각 유지. 그러나 **IS_ERR 서브셋**은 "return-value-as-error" 이디엄으로 longjmp 보다 훨씬 흔하고 local, 완화된 부분집합으로 채택.

**LOC**: ~120 / **난이도**: med
**우선순위**: ★★ (2순위)

---

## Frontier G3 — variadic forwarding wrapper (제한적 va_list)

### 패턴 스케치
```c
static void log_write_v(const char *fmt, va_list ap) {
    vsnprintf(buf, sizeof(buf), fmt, ap);
    writel(buf[0], REG_DEBUG);           // sink, taint from fmt/ap
}
static void log_write(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    log_write_v(fmt, ap);                // forward
    va_end(ap);
}
void caller(u32 user) { log_write("%x", user); }   // user → sink
```

### 왜 현재 놓치는가
- `_find_callers_with_args` 는 호출 인자 index 기반 매칭. variadic `...` 는 index 가 유동이라 taint 가 끊긴다.
- `ts_parser` 가 `va_start`/`va_arg` 를 식별하지 않음 → `va_list ap` 는 origin 없는 변수로 간주되어 `_trace_backward` 가 조기 종료.

### 구현 힌트 (부분집합 전략)
- **대상 제한**: "variadic 함수가 자기 `...` 를 **다른 variadic/va_list 함수로 그대로 forward**" 하는 1-hop 케이스만.
- **ts_parser**: 함수 시그니처에 `...` 가 있는 경우 `is_variadic=True` 저장. 함수 본문에 `va_start(ap, fmt)` 가 있고 `ap` 가 다른 호출의 인자로 그대로 전달되면 `variadic_forward_edge` 추출.
- **taint_tracker._find_callers_with_args**: callee 가 `is_variadic` 이면 arg index >= fixed_param_count 인 호출 인자들을 모두 taint source 로 취급 (over-approx, confidence=medium).
- 완전한 va_arg 타입 해석은 skip.

**기각 재검토 노트**: 전체 va_list semantics (va_copy, nested va_arg) 는 여전히 기각. forwarding 서브셋만 채택.

**LOC**: ~100 / **난이도**: hard (경계조건 많음)
**우선순위**: ★ (3순위)

---

## 우선순위 요약

| 순위 | ID | 패턴 | LOC | 난이도 |
|------|----|------|-----|--------|
| 1 | G1 | fnptr local-alias indirect call | ~80  | med  |
| 2 | G2 | IS_ERR/PTR_ERR pointer source + guard | ~120 | med  |
| 3 | G3 | variadic forward (1-hop subset) | ~100 | hard |

**권장:** 다음 진화 사이클은 G1 단독 구현 → 벤치마크 fixture 2~3건 추가 → regression 확인 후 G2 착수.
