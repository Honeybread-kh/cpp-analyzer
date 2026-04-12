# Evolution Proposal — 2026-04-13

**Current state:** 45/45 (100%), no gaps in existing benchmark.

진화 방향은 3축으로 구성: (A) 벤치마크 확장, (B) 성능 최적화, (C) 분석 정확도 개선.

---

## A. 벤치마크 확장 (새 패턴 추가)

### Gap A1: 함수 포인터를 통한 간접 호출 (hard)
**패턴:**
```c
typedef void (*hw_write_fn)(int reg, int val);
void apply_config(Config* cfg, hw_write_fn writer) {
    writer(TIMING_REG, cfg->frequency);
}
```
**영향도:** 드라이버 추상화 계층(HAL)에서 흔함. 커널, RTOS, DPDK.
**구현 힌트:**
- ts_parser.py: `extract_function_pointer_calls()` — `pointer_expression`으로 호출되는 패턴
- taint_tracker.py: `_trace_backward()`에서 함수 포인터 인자 발견 시, 할당 지점 추적하여 실제 함수 결정

### Gap A2: union 타입 필드 (medium)
**패턴:**
```c
union { uint32_t raw; struct { uint16_t lo, hi; } parts; } reg_val;
reg_val.parts.lo = cfg->frequency;
regs->regs[X] = reg_val.raw;
```
**영향도:** 레지스터 패킹, 네트워크 프로토콜 헤더.
**구현 힌트:** ts_parser의 `extract_struct_fields()`를 확장하여 union_specifier도 처리.

### Gap A3: volatile 레지스터 포인터 직접 접근 (medium)
**패턴:**
```c
*(volatile uint32_t*)0x40001000 = cfg->frequency;
((volatile HwRegs*)HW_BASE)->regs[TIMING_REG] = val;
```
**영향도:** MMIO 드라이버, 베어메탈.
**구현 힌트:** sink 패턴에 `\*\s*\(\s*volatile` regex 추가. taint_tracker의 `_match_sink`에 cast_expression 처리.

### Gap A4: 콜백 기반 이벤트 전달 (hard)
**패턴:**
```c
static Config* g_pending_cfg;
void on_timer_tick(void) { apply_register(g_pending_cfg->frequency); }
void schedule(Config* c) { g_pending_cfg = c; register_callback(on_timer_tick); }
```
**영향도:** 이벤트 기반 드라이버, 인터럽트 핸들러.
**구현 힌트:** 글로벌 변수 추적(이미 있음)을 콜백 등록과 연결.

### Gap A5: 구조체 배열 인덱싱 (medium)
**패턴:**
```c
ChannelConfig channels[4];
for (int i = 0; i < 4; i++) regs->regs[CH_BASE+i] = channels[i].threshold;
```
**영향도:** 멀티 채널 HW, 센서 어레이.
**구현 힌트:** subscript_expression 인덱스가 변수인 경우 symbolic tracking. 실용적으로는 "i-범위 전체"로 근사.

---

## B. 성능 최적화 (대규모 프로젝트 대응)

### Gap B1: 증분 분석 (medium)
**문제:** 현재 `trace()`가 매번 전체 파일 재파싱.
**해결:**
- DB에 파싱 결과(assignments, enums, ranges) 저장 + file hash
- `_load_all_files()`를 수정하여 hash 일치하면 DB에서 로딩
**구현 힌트:**
- db/schema.py: `file_parse_cache` 테이블 (file_id, content_hash, assignments_json, enums_json, ranges_json)
- taint_tracker.py: `_load_all_files()` 확장

### Gap B2: 병렬 파싱 (medium)
**문제:** 싱글 스레드로 수천 파일 파싱 시 분 단위.
**해결:** `multiprocessing.Pool`로 파일별 parse → 결과 병합.
**구현 힌트:** `_load_all_files()` 내 for 루프를 pool.map으로 교체. tree-sitter는 프로세스 격리로 GIL 우회.

### Gap B3: 경로 폭발 방지 (easy)
**문제:** `_trace_backward()`에서 경로 분기가 많으면 지수 증가.
**해결:** `max_paths` 파라미터로 전체 경로 수 제한 (이미 부분적으로 구현된 듯). 우선순위 큐로 짧은 경로부터.

---

## C. 분석 정확도 개선

### Gap C1: 매크로 확장 해석 (hard)
**문제:** `REG_WRITE(TIMING_REG, val)`은 인식하지만, 매크로 내부의 비트 조작은 미추적.
**예:**
```c
#define SET_FIELD(reg, val, field) reg = (reg & ~FIELD_MASK) | ((val) << FIELD_SHIFT)
SET_FIELD(regs[X], cfg->mode, MODE_FIELD);
```
**해결:** libclang preprocessor 확장 결과 사용 (이미 libclang 의존성 있음).
**구현 힌트:** 매크로 정의를 파싱하여 bit field 위치/shift 추출.

### Gap C2: 타입 캐스팅 통과 추적 (medium)
**패턴:**
```c
uint32_t raw = (uint32_t)cfg;
regs[X] = ((Config*)raw)->frequency;
```
**해결:** cast_expression을 노출하여 taint 유지.

### Gap C3: false negative — 포인터 산술 (medium)
**패턴:**
```c
uint32_t* p = &regs->regs[0]; p += TIMING_OFFSET; *p = cfg->frequency;
```
**해결:** pointer_expression에서 offset 계산 후 sink 매칭.

### Gap C4: range constraint 고도화 (easy)
**현재:** `if (x < MIN) x = MIN;` 패턴만 감지.
**확장:**
- `x = CLAMP(x, MIN, MAX);` 매크로
- `x = x > MAX ? MAX : x;` ternary clamp
- `assert(x >= MIN && x <= MAX);` 검증문
**구현 힌트:** ts_parser.extract_range_constraints()에 패턴 추가.

---

## 우선순위 (권장)

**가장 실용적 (ROI 높음):**
1. **Gap C4** (easy) — range 패턴 확장. 실제 코드에서 다양한 clamp 스타일 커버
2. **Gap A3** (medium) — volatile MMIO 직접 접근. 베어메탈 드라이버의 핵심 패턴
3. **Gap A2** (medium) — union 타입. 레지스터 패킹에서 필수
4. **Gap B1** (medium) — 증분 분석. 대규모 프로젝트 필수 (cpp-analyzer가 이미 증분 indexing 지원)

**큰 그림 (hard):**
5. **Gap A1** (hard) — 함수 포인터. HAL 추상화 지원
6. **Gap C1** (hard) — 매크로 확장. bit field 정밀 분석

---

## Gap 1 추천: Gap C4 + A3 묶음 (easy/medium)

실용성 높고 구현 범위 작음. 둘을 한 번에 처리 가능:
- ts_parser에 range 패턴 3종 추가 (CLAMP 매크로, ternary clamp, assert)
- sink 패턴에 volatile 포인터 cast 추가
- 벤치마크에 `volatile_mmio_write`, `clamp_macro_write`, `ternary_clamp_write` 3개 추가
