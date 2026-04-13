---
name: cpp-analyzer-mine
description: "외부 C/C++ OSS 저장소(Linux kernel, Zephyr, FreeRTOS 등)에서 taint/dataflow 분석 관점의 idiom 후보를 채굴하는 휴리스틱 카탈로그. container_of, fnptr table, goto unwind, IS_ERR guard, va_list, MMIO accessor, bitfield, memcpy blob 등 정해진 패턴을 ripgrep으로 찾고 함수 경계에서 ≤40줄 스니펫을 추출한다. miner 에이전트가 사용."
---

# cpp-analyzer Mining Skill

외부 C/C++ 코드에서 fixture 후보 idiom을 찾는 재현성 있는 휴리스틱.

## 왜 이 스킬이 필요한가

miner가 자유롭게 grep하면 실행마다 결과가 달라지고, 노이즈가 폭증한다. 이 스킬은 **고정된 패턴 카탈로그**를 제공해 재현성과 포커스를 확보한다.

## 필수 전제

- `/tmp/curator_sources/<repo>/` 에 shallow clone 되어 있어야 함 (miner가 처리)
- ripgrep (`rg`) 사용 가능
- repo당 최대 30 후보 — 초과 시 드랍

## 패턴 카탈로그

각 패턴은 **regex + 후처리 규칙**으로 구성된다.

### P1. container_of chain
```
rg -n 'container_of\s*\(' --type c
```
- 후처리: 매칭 라인 주변 ±15줄 읽기. `container_of` 결과를 다시 member 접근 (`->`)하는 흐름이 있으면 후보로 등록
- `kind`: `container_of_chain`

### P2. Function-pointer designated-init table
```
rg -nU '=\s*\{[\s\S]{0,400}?\[\w+\]\s*=\s*\w+' --type c
```
- 후처리: 배열 초기자가 함수명만 포함하는지 확인 (숫자/문자열이면 드랍)
- `kind`: `fnptr_designated_table`

### P3. goto-based error unwind
```
rg -n 'goto\s+(err_|out_|unwind_|free_)\w*\s*;' --type c
```
- 후처리: 함수 내 라벨이 정의되어 있고, 라벨 뒤에 `<sink>` 가 있는 경우만 등록
- `kind`: `goto_unwind`

### P4. IS_ERR / PTR_ERR pointer guard
```
rg -n 'IS_ERR\s*\(' --type c
```
- 후처리: 같은 함수 내에서 `devm_*_init`, `ioremap`, `clk_get` 등 pointer-return source가 있으면 후보
- `kind`: `is_err_guard`

### P5. va_list forwarding
```
rg -n 'va_start\s*\(' --type c
```
- 후처리: 같은 함수가 다른 variadic/va_list 함수로 `ap` 를 전달하는지 확인
- `kind`: `va_list_forward`

### P6. MMIO accessor sinks
```
rg -n '\b(writel|writeq|iowrite32|iowrite64|__raw_writel|regmap_write)\s*\(' --type c
```
- 후처리: 첫 인자 혹은 value 인자가 변수(상수 아님)인 경우만 등록
- `kind`: `mmio_accessor`

### P7. Bitfield / packed struct
```
rg -nU 'struct\s+\w+\s*\{[\s\S]{0,600}:\s*\d+' --type c
```
- 후처리: 해당 struct의 필드를 실제 assign하는 함수가 있는지 확인
- `kind`: `bitfield_packed`

### P8. memcpy / memmove blob copy
```
rg -n '\b(memcpy|memmove|__builtin_memcpy)\s*\(' --type c
```
- 후처리: src가 구조체 포인터이고 dst가 local struct인 경우만 등록 (`sizeof` 또는 `sizeof(*x)` 포함)
- `kind`: `memcpy_blob`

### P9. Linked-list walk (bonus)
```
rg -n 'list_for_each_entry\s*\(' --type c
```
- 후처리: 루프 바디 안에 sink 호출이 있으면 후보
- `kind`: `linked_list_walk`

## 스니펫 추출 규칙

1. 매칭 라인 기준 함수 경계 찾기 — 가장 가까운 `^{`와 짝 맞는 `^}` 사이
2. 함수가 40줄 초과면 매칭 라인 기준 ±20줄 (최대 40줄)로 잘라내고 `truncated: true` 플래그
3. 스니펫 시작 전에 `/* --- snippet from <file>:<line_start> (truncated: ...) --- */` 주석 추가 (fixture-writer가 라이선스-safe 재작성 시 제거)

## 중복 제거

같은 repo의 같은 파일에서 같은 `kind` 가 3건 이상이면 novelty hint 가장 높은 1건만 채택. novelty hint는:
- 파일 전체 평균 identifier 다양성
- 매칭 라인 주변에 다른 패턴(P1~P9)이 함께 등장하는가 (combinatorial bonus +1)

## 출력 스키마

miner가 채움. 이 스킬은 휴리스틱만 제공.

## 에러 핸들링

- ripgrep 미설치 → `apt-get`/`brew` 가 아닌 에이전트가 즉시 보고하고 중단 (설치는 사람 영역)
- 패턴 매칭 0건 → 정상, 빈 배열 반환
- 매우 큰 파일(>100KB)은 skip (통상 auto-generated)
