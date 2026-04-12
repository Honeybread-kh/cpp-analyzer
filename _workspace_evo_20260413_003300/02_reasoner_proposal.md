# Evolution Proposal -- 2026-04-12

## 현재 상태
- 점수: 21/21 (100.0%)
- 기존 gap: 없음 (이전 15/21에서 inter_procedural 2건 해결하여 100% 달성)
- 카테고리: basic(5/5), alias_tracking(1/1), macro_sink(2/2), conditional_tracking(1/1), compound_assignment(1/1), inter_procedural(2/2)

기존 벤치마크를 모두 통과하므로, 이 제안서는 **벤치마크 커버리지 자체를 확장**하여 분석기의 실제 한계를 드러내는 새 패턴을 제안한다.

## 커버리지 확장 제안

### 제안 1: 삼항 연산자(ternary) 데이터플로우

- **요구 능력:** `ternary_tracking` (신규 카테고리)
- **패턴 설명:** `condition ? source_a : source_b` 형태에서 양쪽 분기 모두의 taint를 추적해야 함
- **C 코드 예시:**
```c
void ternary_write(Config* cfg, HwRegs* regs) {
    uint32_t val = cfg->enable ? cfg->frequency : 0;
    regs->regs[CTRL_REG] = val;
}
```
- **현재 한계:**
  - `ts_parser.py::_extract_variables` (L723-753): `conditional_expression` 노드를 재귀적으로 탐색하긴 하지만, `walk_type`이 `field_expression`과 `identifier`만 수집하므로 **ternary 자체의 구조는 인식하지 않음**
  - `taint_tracker.py::_find_reaching_defs` (L422-435): `val`의 reaching def를 찾으면 init_declarator의 RHS로 `cfg->enable ? cfg->frequency : 0`을 얻고, `_extract_variables`가 `cfg->enable`과 `cfg->frequency`를 추출할 수 있음
  - **예상 결과:** 현재 코드가 이미 동작할 가능성이 높음. `_extract_variables`가 ternary 내부의 field_expression을 재귀로 탐색하기 때문. 벤치마크 추가로 **확인이 필요**
- **제안 변경:**
  - Tier 0 (테스트만): `hw_model.c`에 ternary 패턴 추가 + `expected.yaml`에 엔트리 추가
  - Tier 3 (실패 시): `_extract_variables`에서 `conditional_expression`의 consequence/alternative를 명시적으로 분기 처리
  - 예상 LOC: ~15줄 (fixture + yaml), 분석기 변경 0~10줄
- **부작용 검토:** 기존 테스트에 영향 없음 (새 함수 추가)
- **예상 난이도:** 하

---

### 제안 2: 글로벌 변수 경유 데이터플로우

- **요구 능력:** `global_tracking` (신규 카테고리)
- **패턴 설명:** config 값이 전역 변수에 저장된 뒤, 다른 함수에서 그 전역 변수를 읽어 레지스터에 쓰는 패턴. 임베디드 코드에서 매우 흔함.
- **C 코드 예시:**
```c
static int g_cached_freq;

void cache_config(Config* cfg) {
    g_cached_freq = cfg->frequency;
}

void apply_cached(HwRegs* regs) {
    regs->regs[TIMING_REG] = g_cached_freq;
}
```
- **현재 한계:**
  - `ts_parser.py::extract_all_assignments` (L521-600): `function_definition` 내부만 탐색 (`walk_type(root, "function_definition")`). **파일 스코프 전역 변수 초기화는 함수 바깥이므로 추출되지 않음**
  - `taint_tracker.py::_trace_backward` (L264-401): `_is_param` 분기와 `_find_cross_func_field_writers` 분기가 있지만, 둘 다 **구조체 필드 기반 매칭**에 의존. 단순 전역 변수(`g_cached_freq` 같은 plain identifier)에 대한 cross-function 링크가 없음
  - **실패 지점:** `_trace_backward`에서 `g_cached_freq`를 `apply_cached` 함수의 assignment RHS에서 발견하지만, `_is_param` 체크에서 False 반환 (전역 변수는 파라미터가 아님). `_find_reaching_defs`도 같은 함수 내 assignment만 검색하므로 `cache_config`의 assignment를 찾지 못함
- **제안 변경:**
  - Tier 1 (파서 확장): `extract_all_assignments`에서 함수 바깥 전역 변수 assignment도 추출 (function="" 으로 마킹)
  - Tier 3 (분석 로직): `_trace_backward`에 "파라미터도 아니고 같은 함수 내 def도 없는 변수 → 다른 함수에서 같은 이름의 LHS를 가진 assignment 검색" 분기 추가. `_find_cross_func_field_writers`와 유사하지만 plain variable 버전
  - 예상 LOC: ~20줄 (fixture + yaml) + ~25줄 (분석기)
- **부작용 검토:** 전역 변수 이름이 흔한 이름(예: `val`, `tmp`)이면 false positive 위험. 이름 매칭 시 `g_` 접두사나 static 키워드 같은 힌트를 활용하거나, 같은 파일 내로 범위를 제한하면 안전
- **예상 난이도:** 중

---

### 제안 3: 배열 인덱스 경유 데이터플로우

- **요구 능력:** `array_element_tracking` (신규 카테고리)
- **패턴 설명:** config 값을 배열 원소에 저장한 뒤, 그 배열 원소를 읽어 레지스터에 쓰는 패턴. LUT(Look-Up Table) 기반 HW 설정에서 흔함.
- **C 코드 예시:**
```c
void array_write(Config* cfg, HwRegs* regs) {
    uint32_t params[4];
    params[0] = cfg->frequency;
    params[1] = cfg->mode;
    regs->regs[TIMING_REG] = params[0];
    regs->regs[MODE_REG] = params[1];
}
```
- **현재 한계:**
  - `taint_tracker.py::_find_reaching_defs` (L422-435): LHS 매칭이 문자열 비교(`lhs == var`). `params[0]`과 `params[0]`은 매칭되지만, 인덱스가 변수인 경우(`params[i]`)는 **인덱스 값 추적이 불가**
  - 상수 인덱스(`params[0]`)의 경우, 현재 코드가 문자열 매칭으로 **이미 동작할 가능성**이 있음. 확인 필요.
- **제안 변경:**
  - Tier 0 (테스트만): 상수 인덱스 패턴을 fixture에 추가하여 현재 동작 여부 확인
  - Tier 3 (실패 시): `_find_reaching_defs`에서 subscript_expression의 base 배열명을 매칭하는 로직 추가
  - 예상 LOC: ~15줄 (fixture + yaml) + 0~15줄 (분석기)
- **부작용 검토:** 상수 인덱스 매칭은 안전. 변수 인덱스 매칭은 scope 밖이므로 이번에는 하지 않음
- **예상 난이도:** 하~중

---

### 제안 4: 구조체 복사(memcpy / struct assign) 데이터플로우

- **요구 능력:** `struct_copy_tracking` (신규 카테고리)
- **패턴 설명:** 구조체 전체가 복사(`=` 또는 `memcpy`)된 뒤, 복사본의 필드를 통해 레지스터에 기록되는 패턴.
- **C 코드 예시:**
```c
void struct_copy_write(Config* cfg, HwRegs* regs) {
    Config local_cfg = *cfg;
    regs->regs[THRESH_REG] = local_cfg.threshold;
}
```
- **현재 한계:**
  - `taint_tracker.py::_build_alias_map` (L403-419): `lhs`에 `->` 또는 `.`가 없는 단순 변수 할당만 alias로 등록. `Config local_cfg = *cfg`는 init_declarator로 추출되며 `lhs="local_cfg"`, `rhs="*cfg"`. alias_map은 `*` 접두사를 `lstrip("&*")`로 제거하므로 `local_cfg → cfg`로 등록됨
  - `AliasMap::resolve_field` (L80-92): `local_cfg.threshold` → `cfg.threshold`로 변환. 하지만 원본이 포인터(`cfg->threshold`)이고 복사본은 값 타입(`local_cfg.threshold`)이므로 `.` vs `->` 접근자 불일치 발생
  - **실패 지점:** `resolve_field`가 `local_cfg.threshold` → `cfg.threshold`를 반환하지만, source 패턴이 `cfg->threshold`를 기대하므로 매칭 실패 가능성
- **제안 변경:**
  - Tier 3 (분석 로직): `AliasMap::resolve_field` 또는 `_match_source`에서 `->` 와 `.` 를 동치로 취급하는 로직 추가. 또는 `resolve_field`에서 alias 대상이 포인터(`*`로 역참조)인 경우 separator를 `->` 로 교체
  - 예상 LOC: ~15줄 (fixture + yaml) + ~10줄 (분석기)
- **부작용 검토:** `.` 와 `->` 동치 처리는 C에서 의미가 다르지만, taint 추적에서는 필드 이름이 같으면 동일 데이터 흐름으로 간주해도 안전. 기존 alias_tracking 테스트에 영향 없음 (기존은 모두 `->` 사용)
- **예상 난이도:** 하~중

---

### 제안 5: 함수 포인터 / 콜백 경유 데이터플로우

- **요구 능력:** `callback_tracking` (신규 카테고리)
- **패턴 설명:** 함수 포인터를 통해 간접 호출된 함수가 config 값을 레지스터에 전달하는 패턴. 드라이버 코드의 ops 테이블에서 흔함.
- **C 코드 예시:**
```c
typedef void (*write_fn)(Config*, HwRegs*);

void do_write(Config* cfg, HwRegs* regs) {
    regs->regs[MODE_REG] = cfg->mode;
}

void dispatch(Config* cfg, HwRegs* regs) {
    write_fn fn = do_write;
    fn(cfg, regs);
}
```
- **현재 한계:**
  - `ts_parser.py::extract_call_arguments` (L633-671): `callee_name`으로 `node_text(callee_node)`를 사용. `fn(cfg, regs)` 호출에서 callee_name은 `"fn"`이 되며, 이는 실제 함수 이름 `do_write`와 연결되지 않음
  - `taint_tracker.py::_func_to_file` (L127): 함수 정의 기반으로 구축되므로 `fn`은 등록되지 않음
  - **실패 지점:** `_trace_backward`가 `fn` 호출의 return value나 parameter를 추적하려 해도 `fn`이 `_func_to_file`에 없으므로 inter-procedural 분석이 시작조차 안 됨
- **제안 변경:**
  - Tier 1 (파서 확장): `extract_all_assignments`에서 init_declarator의 RHS가 함수 이름(identifier로서 `_func_to_file`에 등록된 것)인 경우 "function pointer alias"로 마킹
  - Tier 3 (분석 로직): `_trace_backward`에서 call의 callee가 `_func_to_file`에 없을 때, alias_map에서 resolve하여 실제 함수명을 얻는 분기 추가
  - 예상 LOC: ~20줄 (fixture + yaml) + ~30줄 (분석기)
- **부작용 검토:** 함수 포인터가 조건부로 재할당되는 경우 (`if (x) fn = a; else fn = b;`) 잘못된 함수로 연결될 위험. 첫 구현에서는 단일 할당만 지원하고 visited set으로 무한루프 방지
- **예상 난이도:** 상

---

### 제안 6: 복수 reaching definition (phi-node)

- **요구 능력:** `multi_reaching_def` (신규 카테고리)
- **패턴 설명:** 같은 변수에 대해 if/else 양쪽에서 서로 다른 config 값을 대입한 뒤, 그 변수를 레지스터에 쓰는 패턴. 현재 conditional_tracking은 조건 내부의 *직접* 레지스터 쓰기만 테스트하고, 조건 이후 합류 지점은 테스트하지 않음.
- **C 코드 예시:**
```c
void phi_write(Config* cfg, HwRegs* regs) {
    uint32_t val;
    if (cfg->enable) {
        val = cfg->frequency;
    } else {
        val = cfg->threshold;
    }
    regs->regs[TIMING_REG] = val;
}
```
- **현재 한계:**
  - `taint_tracker.py::_find_reaching_defs` (L422-435): `reversed(assignments)` 순회에서 첫 번째 매칭에 `break`. if/else 양쪽의 assignment 중 **하나만** 반환. `extract_all_assignments`가 if/else 내부 assignment를 별개 엔트리로 추출하므로 마지막 것(else 분기)만 도달
  - **실패 지점:** `val`에 대한 reaching def가 `val = cfg->threshold` (else 분기)만 반환. `val = cfg->frequency` (if 분기)는 누락. 결과적으로 cfg->frequency → TIMING_REG 경로를 놓침
- **제안 변경:**
  - Tier 3 (분석 로직): `_find_reaching_defs`에서 조건 분기 내부의 assignment인 경우 (같은 line range의 if_statement 내부) 양쪽 def를 모두 반환하도록 수정. 또는 단순히 `break` 제거 후 모든 def를 반환하고 `_trace_backward`에서 각각 시도
  - 예상 LOC: ~15줄 (fixture + yaml) + ~15줄 (분석기)
- **부작용 검토:** `break` 제거 시 루프 내 재할당 패턴(`for (...) { val = ...; }`)에서 불필요한 다중 def가 나올 수 있음. 성능에 약간 영향 있지만 correctness 상 더 안전. visited set이 무한루프를 방지
- **예상 난이도:** 중

---

### 제안 7: 비트필드 / 시프트+마스크 역추적

- **요구 능력:** `bitfield_tracking` (신규 카테고리)
- **패턴 설명:** 레지스터 값을 비트필드 방식으로 조합하는 패턴. 현재 compound_assignment 테스트는 `|=` 체인만 테스트하지만, 실무에서는 시프트 후 OR, 마스크 후 대입이 복합적으로 사용됨.
- **C 코드 예시:**
```c
void bitfield_write(Config* cfg, HwRegs* regs) {
    uint32_t reg_val = 0;
    reg_val = (cfg->mode & 0xFF) | ((cfg->frequency & 0xFFF) << 8) | ((cfg->enable & 0x1) << 20);
    regs->regs[CTRL_REG] = reg_val;
}
```
- **현재 한계:**
  - `_extract_variables`가 이 복합 표현식에서 `cfg->mode`, `cfg->frequency`, `cfg->enable`을 추출할 수 있어야 함. `field_expression` 타입을 재귀로 찾으므로 **동작할 가능성이 높음**.
  - 실제로 현재 `direct dimension pack` 테스트가 `cfg->width | (cfg->height << 16)` 패턴을 이미 통과하므로, 마스크가 추가된 것이 문제될 가능성은 낮음
- **제안 변경:**
  - Tier 0 (테스트만): fixture에 패턴 추가하여 현재 동작 확인
  - Tier 3 (실패 시): `_extract_variables`가 `binary_expression` 깊이를 제한하는지 확인 후 수정
  - 예상 LOC: ~12줄 (fixture + yaml)
- **부작용 검토:** 없음 (새 함수 추가)
- **예상 난이도:** 하

---

## 우선순위

| 순위 | 제안 | 카테고리 | 이유 |
|------|------|----------|------|
| 1 | 제안 6: 복수 reaching def | `multi_reaching_def` | `_find_reaching_defs`의 `break` 제한은 실질적 분석 버그. 코드 변경 최소, 영향 큼 |
| 2 | 제안 2: 글로벌 변수 경유 | `global_tracking` | 임베디드 코드에서 매우 흔한 패턴. 분석기의 함수 스코프 한계를 드러냄 |
| 3 | 제안 1: 삼항 연산자 | `ternary_tracking` | 이미 동작할 가능성 높으나 확인 필요. 비용 최소 |
| 4 | 제안 7: 비트필드 시프트+마스크 | `bitfield_tracking` | 이미 동작할 가능성 높으나 확인 필요. 비용 최소 |
| 5 | 제안 3: 배열 인덱스 경유 | `array_element_tracking` | 상수 인덱스는 동작 가능, 테스트로 확인 |
| 6 | 제안 4: 구조체 복사 | `struct_copy_tracking` | `.` vs `->` 불일치 수정 필요하지만 영향 범위 작음 |
| 7 | 제안 5: 함수 포인터 | `callback_tracking` | 난이도 높고 false positive 위험. 다른 제안 해결 후 진행 |

## 권장 첫 구현 범위

**1차 배치 (제안 1, 3, 7):** 이미 동작할 가능성이 높은 패턴을 fixture/yaml에 추가하여 현재 분석기의 실제 커버리지를 측정. 분석기 코드 변경 없이 벤치마크만 확장.

**2차 배치 (제안 6):** `_find_reaching_defs`의 `break` 제한 수정. 가장 임팩트가 큰 코드 변경이면서 LOC가 적음.

**3차 배치 (제안 2, 4):** cross-function plain variable 추적과 struct copy alias 수정. 중간 난이도.

**4차 배치 (제안 5):** 함수 포인터 지원. 설계 변경이 크므로 별도 PR로 진행.

## 비권장 사항

- `taint_tracker.py` 전체 재작성 금지 -- 현재 100% 로직이 검증됐으므로 부분 확장이 안전
- `_extract_variables`의 재귀 구조 변경 금지 -- 모든 기존 패턴이 이 함수에 의존
- 변수 인덱스 배열 추적(`arr[i]`) 시도 금지 -- 인덱스 값 추적은 사실상 symbolic execution 영역이며 현재 아키텍처와 맞지 않음
