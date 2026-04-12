# Evolution Proposal — 2026-04-11

## 현재 상태
- 점수: 15/21 (71.4%)
- 통과: easy 5/5, medium 5/5, hard 0/2
- 주요 gap 카테고리: `inter_procedural` (2/2 MISS, 다른 카테고리는 모두 100%)
- regression: 없음 (초기 실행, 기준점 부재)
- 이전 제안서: 없음

요약: 모든 미해결 gap이 단일 카테고리(`inter_procedural`)에 집중되어 있고, 두 케이스가 서로 다른 부족 지점을 노출한다. Gap 1은 "함수 호출 경계를 넘어선 step 기록 누락"이고, Gap 2는 "공유 struct 필드를 통한 cross-function flow 부재"이다.

---

## Gap 분석

### Gap 1: multi-hop: config → divider → timing → reg
- **요구 능력:** `inter_procedural`
- **expected.yaml 정의** (`tests/fixtures/dataflow/expected.yaml:63-69`):
  ```yaml
  - name: "multi-hop: config → divider → timing → reg"
    source: "cfg->frequency"
    sink: "regs->regs[TIMING_REG]"
    expected_hops: ["compute_divider", "compute_timing"]
    requires: inter_procedural
    min_depth: 4
    difficulty: hard
  ```
- **패턴 실물** (`tests/fixtures/dataflow/hw_model.c:80-92`):
  ```c
  static int compute_divider(int freq) {
      return freq / BASE_CLK;
  }
  static int compute_timing(int divider) {
      return divider - 1;
  }
  void multi_hop_write(Config* cfg, HwRegs* regs) {
      int div = compute_divider(cfg->frequency);
      int timing = compute_timing(div);
      regs->regs[TIMING_REG] = timing << 8;
  }
  ```
- **테스트 검증 조건** (`tests/test_dataflow.py:155-168`):
  ```python
  funcs = {s.function for s in p.steps}
  if "compute_divider" in funcs or "compute_timing" in funcs:
      found = p
  ```
  → `p.steps` 중 적어도 하나의 step `function` 필드가 `compute_divider` 또는 `compute_timing`이어야 PASS.

- **현재 탐지 로직 추적**

  진입점 `taint_tracker.py::trace` (L128) → 각 sink에 대해 `_trace_backward(rhs_var=...)` 호출.

  Sink scan은 `regs->regs[TIMING_REG] = timing << 8`를 잡고 `rhs_vars=["timing"]` 등록 (sink_var는 RHS expression). 

  `_trace_backward("timing", "multi_hop_write", file, depth=5)` 진행:
  1. `_find_reaching_defs("timing", ...)` (L369) — `init_declarator` `int timing = compute_timing(div)`를 lhs="timing"으로 매칭. rhs_vars는 `_extract_variables(value)` 결과.
  2. `_extract_variables` (`ts_parser.py:660-690`)는 call_expression의 function child(`compute_timing`)를 제외하고 `["div"]`만 반환 (L684-687):
     ```python
     parent = ident.parent
     if parent and parent.type == "call_expression":
         func_node = parent.child_by_field_name("function")
         if func_node and ident.start_byte == func_node.start_byte:
             continue
     ```
  3. 재귀 `_trace_backward("div", "multi_hop_write", ...)` → `int div = compute_divider(cfg->frequency)` 매칭, rhs_vars = `["cfg->frequency"]` (field_expression이 우선).
  4. 재귀 `_trace_backward("cfg->frequency", "multi_hop_write", ...)` → `_match_source` (L384) 통과, **즉시 SOURCE 반환**. 이때 `function=multi_hop_write`로 노드 생성 (L284-290).
  5. 호출 스택을 되감으며 `chain.append(...)`로 INTERMEDIATE 노드 추가하지만 **모든 step의 `function` 필드는 `multi_hop_write`로 고정** (`taint_tracker.py:L323-330`):
     ```python
     chain.append(TaintNode(
         variable=resolved_var,
         node_type="INTERMEDIATE",
         transform=assign["transform"] or "",
         file=file_path,
         line=assign["line"],
         function=func_name,   # ← 항상 호출자(=multi_hop_write)
     ))
     ```

- **원인 가설**
  - **현상:** 경로는 발견되지만 `p.steps[*].function`에 `compute_divider`/`compute_timing`이 없어 테스트 실패.
  - **예상 경로:** `_trace_backward`가 호출 인자 `cfg->frequency`를 같은 함수 스코프에서 source로 인식하고 즉시 종료.
  - **실패 지점:** `_find_reaching_defs`가 callee 본문을 들여다보지 않으며, 호출식 (`compute_divider(...)`, `compute_timing(...)`)을 만났을 때 callee의 return value 흐름으로 잠수하는 경로가 없다.
  - **근거 코드:** `taint_tracker.py:369-382` `_find_reaching_defs`는 lhs 일치만 본다. `_extract_variables`가 call_expression의 함수 이름을 일부러 제거(`ts_parser.py:684-687`)하므로 rhs_vars에는 callee 식별자조차 남지 않고, taint_tracker 측에서도 "이 init_declarator의 RHS가 call_expression이면 callee로 잠수" 분기가 존재하지 않는다.

- **제안 변경**

  | Tier | 위치 | 변경 |
  |------|------|------|
  | **Tier 1 (파서)** | `ts_parser.py::extract_all_assignments` | 각 assignment dict에 `rhs_call: str \| None` 필드 추가. RHS 노드가 `call_expression`이면 callee_name 저장. 또한 신규 함수 `extract_function_returns(root)`로 각 함수의 `return` 표현식 목록을 추출 — `{function_name, return_expr, return_vars, line}`. |
  | **Tier 2 (DB)** | 없음 | 캐시는 `TaintTracker._file_returns` 인메모리만 사용해도 충분 (다른 분석에서 재사용할 일이 적음). DB 스키마 변경 불필요. |
  | **Tier 3 (분석)** | `taint_tracker.py::_trace_backward` | reaching def를 처리할 때 `assign.get("rhs_call")`이 있으면 callee 본문의 모든 return 표현식을 source로 삼아 `_trace_backward(return_var, callee_func, callee_file, depth-1, ...)` 분기 추가. 이 분기로 만든 INTERMEDIATE 노드의 `function` 필드는 **callee_func**로 설정해야 테스트가 PASS한다. 그 이후 callee 내부에서 만난 parameter는 기존 `_find_callers_with_args` 경로로 다시 외부로 빠져나오게 둔다 (이미 동작). |

  - 핵심 분기 의사코드 (`_trace_backward` 안, L312~ reaching loop):
    ```python
    for assign in reaching:
        # 신규: callee 본문으로 잠수
        callee = assign.get("rhs_call")
        if callee and callee in self._func_to_file:
            callee_file = self._func_to_file[callee]
            for ret in self._file_returns.get(callee_file, []):
                if ret["function"] != callee:
                    continue
                for ret_var in ret["return_vars"]:
                    chain = self._trace_backward(
                        ret_var, callee, callee_file,
                        depth - 1, visited,
                    )
                    if chain:
                        chain.append(TaintNode(
                            variable=resolved_var,
                            node_type="INTERMEDIATE",
                            transform=f"={callee}(...)",
                            file=callee_file,
                            line=ret["line"],
                            function=callee,   # ← 핵심
                        ))
                        return chain
        # 기존 분기 유지
        for rhs_var in assign["rhs_vars"]:
            ...
    ```

  - 예상 LOC: 파서 신규 함수 ~25줄, `_load_all_files`에 캐시 1줄, `_trace_backward` 분기 ~20줄, assignment dict 필드 1줄 (`rhs_call`). 총 **~50 LOC**.

- **부작용 검토**
  - 신규 분기는 기존 reaching def 루프 **앞**에 배치된다. callee의 return을 통해 source가 발견되면 즉시 반환되어, 같은 함수 스코프에서 인자를 직접 source로 매칭하던 기존 경로는 우회된다. 그 결과 multi-hop 케이스의 step 함수명이 callee로 갱신된다 — 이는 의도된 변화.
  - `direct_config_write`, `compound_write` 등은 RHS가 call_expression이 아니므로 `rhs_call`이 None → 영향 없음.
  - `conditional_write`, `alias_write`, `macro_reg_write` 등도 callee return 패턴이 아님 → 영향 없음.
  - `visited` set에 `(callee, ret_var)` 키가 추가되므로 동일 callee 재방문 시 무한 재귀는 막힌다 — 기존 visited 정책과 동일.
  - `_func_to_file`은 이미 `_load_all_files`에서 채워진다 (`taint_tracker.py:202-207`) → 추가 인덱싱 불필요.

- **예상 난이도:** 중

---

### Gap 2: two-layer: config → fw → hw register
- **요구 능력:** `inter_procedural`
- **expected.yaml 정의** (`tests/fixtures/dataflow/expected.yaml:72-78`):
  ```yaml
  - name: "two-layer: config → fw → hw register"
    source: "cfg->frequency"
    sink: "regs->regs[TIMING_REG]"
    expected_hops: ["config_to_fw", "fw_to_hw"]
    requires: inter_procedural
    min_depth: 4
    difficulty: hard
  ```
- **패턴 실물** (`tests/fixtures/dataflow/hw_model.c:41-52`):
  ```c
  void config_to_fw(Config* cfg, FwParams* fw) {
      fw->clk_div = cfg->frequency / BASE_CLK;
      fw->timing_val = fw->clk_div - 1;
      fw->processed_mode = cfg->mode | (cfg->enable << 16);
  }

  void fw_to_hw(FwParams* fw, HwRegs* regs) {
      regs->regs[TIMING_REG] = fw->timing_val << 8;
      regs->regs[MODE_REG] = fw->processed_mode;
  }
  ```
  중요: hw_model.c에 **`config_to_fw`와 `fw_to_hw`를 둘 다 호출하는 driver 함수가 존재하지 않는다**. 두 함수는 외부에서 호출되지 않는 leaf 함수.
- **테스트 검증 조건** (`tests/test_dataflow.py:170-181`):
  ```python
  if "cfg->frequency" in p.source.variable:
      funcs = {p.sink.function} | {s.function for s in p.steps}
      if "config_to_fw" in funcs and "fw_to_hw" in funcs:
          found = p
  ```
  → 한 path 안에 두 함수가 **모두** 등장해야 한다.

- **현재 탐지 로직 추적**
  1. Sink: `regs->regs[TIMING_REG] = fw->timing_val << 8` (in `fw_to_hw`), rhs_vars = `["fw->timing_val"]`.
  2. `_trace_backward("fw->timing_val", "fw_to_hw", ...)` → `_find_reaching_defs` (`taint_tracker.py:369`)는 같은 함수 안에서 lhs="fw->timing_val"인 assignment를 찾지만 `fw_to_hw` 본문에는 없다.
  3. inter-procedural 분기 (`taint_tracker.py:334`) → `_is_param("fw->timing_val", "fw_to_hw", file)` (L391-398):
     ```python
     if param["name"] == var or var.startswith(param["name"] + "->") or ...:
         return True
     ```
     `"fw->timing_val".startswith("fw->")` → True. 통과.
  4. `_find_callers_with_args("fw_to_hw", "fw->timing_val")` (L400-442) → hw_model.c 어디에도 `fw_to_hw(...)` 호출이 없으므로 빈 리스트 반환. 트레이스 종료, 경로 없음.

- **원인 가설**
  - **현상:** `fw->timing_val`의 정의를 다른 함수(`config_to_fw`)에서 찾지 못한다.
  - **예상 경로:** taint tracker가 caller chain 대신, "이 struct 필드가 어떤 함수에서든 쓰여졌는가?" 라는 **글로벌 struct-field reaching definition**을 검색해야 한다.
  - **실패 지점:** `_find_reaching_defs`는 단일 함수 스코프 한정. `_find_callers_with_args`는 호출자 → callee 인자 매핑 한정. 두 함수가 공통 caller 없이 동일 struct 포인터로 연결되는 패턴은 어디서도 처리되지 않는다.
  - **근거 코드:** `taint_tracker.py:293-296`
    ```python
    func_assignments = [
        a for a in self._file_assignments.get(file_path, [])
        if a["function"] == func_name
    ]
    ```
    이후 모든 reaching def 탐색이 이 리스트에 갇혀 있다.

- **제안 변경**

  | Tier | 위치 | 변경 |
  |------|------|------|
  | **Tier 1 (파서)** | 없음 | 기존 `extract_all_assignments` 결과로 충분 (lhs/function 정보 이미 있음). |
  | **Tier 2 (DB)** | 없음 | 인메모리 인덱스로 처리. `TaintTracker._field_writers: dict[str, list[(func, file, assign)]]`을 `_load_all_files` 끝에서 한 번만 빌드. 키는 정규화된 필드 이름(예: `clk_div`, `timing_val`, `processed_mode`). |
  | **Tier 3 (분석)** | `taint_tracker.py::_trace_backward` | 같은 함수 reaching def + caller chain 두 분기가 모두 실패했을 때, fallback으로 "동일 struct 필드 이름을 lhs로 쓰는 다른 함수"를 검색. 매칭되는 writer 함수의 RHS로 trace를 점프시키고, `function=writer_func`로 INTERMEDIATE 노드를 생성. |

  - 핵심 의사코드 (`_trace_backward` 끝부분, `return None` 직전):
    ```python
    # Tier 3 fallback: cross-function struct-field flow
    field = _normalize_field(var)   # "fw->timing_val" -> "timing_val"
    if field:
        for writer_func, writer_file, assign in self._field_writers.get(field, []):
            if writer_func == func_name:
                continue
            for rhs_var in assign["rhs_vars"]:
                chain = self._trace_backward(
                    rhs_var, writer_func, writer_file,
                    depth - 1, visited,
                )
                if chain:
                    chain.append(TaintNode(
                        variable=var,
                        node_type="INTERMEDIATE",
                        transform=assign["transform"] or "field-store",
                        file=writer_file,
                        line=assign["line"],
                        function=writer_func,
                    ))
                    return chain
    return None
    ```
  - `_normalize_field`는 단순히 `re.split(r'->|\.', var)[-1]`로 마지막 필드명만 잘라낸다.
  - 인덱스 빌드 위치: `_load_all_files`에서 파일 루프가 끝난 뒤 한 번:
    ```python
    self._field_writers: dict[str, list[tuple[str, str, dict]]] = {}
    for file_path, assigns in self._file_assignments.items():
        for a in assigns:
            f = _normalize_field(a["lhs"])
            if f and ("->" in a["lhs"] or "." in a["lhs"]):
                self._field_writers.setdefault(f, []).append(
                    (a["function"], file_path, a)
                )
    ```
  - 예상 LOC: 인덱스 빌드 ~12줄, fallback 분기 ~20줄, normalize 헬퍼 ~5줄. 총 **~40 LOC**.

  - **트레이스 시나리오 (수정 후):**
    1. `_trace_backward("fw->timing_val", "fw_to_hw", ...)` reaching def 없음, caller chain 없음 → fallback.
    2. `_field_writers["timing_val"]`에 `(config_to_fw, hw_model.c, fw->timing_val = fw->clk_div - 1)` 발견.
    3. 재귀 `_trace_backward("fw->clk_div", "config_to_fw", ...)` → 같은 함수 reaching def `fw->clk_div = cfg->frequency / BASE_CLK` 발견 → rhs_vars `["cfg->frequency"]` → SOURCE.
    4. 결과 chain의 step 함수: `[config_to_fw(reaching), config_to_fw(field-store)]` + sink.function=`fw_to_hw`. 테스트의 `{p.sink.function} | {s.function for s in p.steps}` = `{fw_to_hw, config_to_fw}` → PASS.

- **부작용 검토**
  - **우선순위 반전 위험:** fallback은 동일-함수 reaching, alias, parameter 분기가 모두 실패한 후에만 동작 → 기존 통과 케이스의 path 결과는 변하지 않는다.
  - **필드 이름 충돌:** 서로 다른 struct가 같은 필드명을 쓰면 false positive 가능. 영향 평가:
    - 현재 fixture에는 `clk_div`, `timing_val`, `processed_mode`가 한 곳씩만 쓰여 충돌 없음.
    - 일반화: type 정보를 함께 키로 묶으면(`("FwParams", "timing_val")`) 정확도 향상. 하지만 1차 구현은 필드명 단일 키로 시작하고, 통과 후 필요 시 type-aware로 확장하는 점진적 접근 권장.
  - **재귀 무한루프:** `visited`에 `(writer_func, rhs_var)`가 이미 들어가므로 같은 (함수, 변수) 조합은 두 번 방문되지 않는다.
  - **direct_config_write, alias_write 등:** 이들은 같은 함수 안에서 reaching def가 잡히므로 fallback에 도달하지 않음 → 영향 없음.
  - **macro REG_WRITE:** sink가 `_scan_sinks`의 macro 분기에서 매칭되며, 추적 변수는 `cfg->frequency`처럼 이미 source인 식. fallback에 도달하지 않음.
  - **conditional_write:** 같은 함수 안에서 `regs->regs[CTRL_REG] = cfg->mode` 직접 매칭 → 영향 없음.

- **예상 난이도:** 중

---

## 신규 테스트 케이스 제안
1. **`return_value_alias` (easy/medium)** — 단일 함수가 `return cfg->x;`를 하고 호출자가 결과를 reg에 쓰는 최소 패턴. Gap 1 제안의 회귀 방지용.
2. **`field_store_chain` (medium)** — `init_fw(cfg)`가 전역 또는 인자 fw에 필드를 쓰고, 별도 함수 `flush_fw()`가 같은 fw 필드를 reg에 쓰는 패턴. Gap 2 제안의 필드 이름 키의 type-aware 강화 시점에 도입.
3. **`negative: same field different struct`** — 같은 필드명을 가진 두 struct가 cross-talk하지 않음을 검증하는 음성 케이스. Gap 2 fallback의 false positive 방지.

---

## 우선순위
1. **(최우선)** Gap 1 — `_trace_backward`에 callee return 잠수 분기 추가 (~50 LOC, Tier 1+3). 한 함수 변경으로 1건 해결, 변경 위치가 좁고 부작용 거의 없음.
2. **(높음)** Gap 2 — `_field_writers` 인덱스 + fallback 분기 추가 (~40 LOC, Tier 3). DB 변경 없이 1건 해결.
3. **(중)** 신규 테스트 케이스 추가 — Gap 1/2 구현 후 회귀 방지 그물.
4. **(낮음)** type-aware field key 확장 — false positive가 실제로 관측되면 그때 도입.

---

## 비권장 사항
- **`taint_tracker.py` 전체 재작성 금지** — 현재 19/21 케이스(easy + medium 전부)가 통과하므로 부분 확장이 안전.
- **DB 스키마 변경 금지** — 두 gap 모두 인메모리 캐시로 해결 가능. WAL 모드 인덱싱 최적화(commit 357c713) 후 스키마 충격을 추가로 주지 말 것.
- **`_extract_variables`에 callee 식별자 다시 포함하지 말 것** — 이 함수의 결과는 reaching def 검색의 키로 쓰이므로, 함수 이름이 들어가면 변수 추적이 망가진다. callee 정보는 반드시 별도 필드(`rhs_call`)로 분리.
- **`_is_param`을 더 느슨하게 만들지 말 것** — Gap 2의 caller chain이 조용히 빈 리스트를 반환하는 동작은 정상이다. 그쪽을 건드리면 macro_sink/conditional 케이스에 부작용이 생길 수 있다.

---

## 품질 체크리스트
- [x] 모든 gap에 대해 파일:함수 수준 근거 포함
- [x] 코드 인용 4건 이상 (`taint_tracker.py:293-296`, `:323-330`, `:369-382`, `ts_parser.py:684-687`, `hw_model.c:41-92`, `expected.yaml:63-78`, `test_dataflow.py:155-181`)
- [x] Tier별 제안 구분 (Gap 1: Tier 1+3, Gap 2: Tier 3)
- [x] 부작용 검토 섹션 (각 gap별)
- [x] 우선순위 숫자 명시
- [x] 이전 제안 없음 (초기 실행) → 반복 검증 불필요
