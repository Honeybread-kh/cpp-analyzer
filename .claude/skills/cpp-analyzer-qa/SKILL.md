---
name: cpp-analyzer-qa
description: "cpp-analyzer 구현 결과를 검증하는 QA 스킬. CLI/MCP 미러링 정합성, DB 스키마-Repository 일치, Analysis-Repository 인터페이스, import 체인, 실제 실행 테스트를 수행. qa 에이전트가 사용."
---

# cpp-analyzer QA Skill

구현된 변경사항의 품질을 계층 간 경계면 교차 비교로 검증한다.

## 검증 워크플로우

```
1. 변경 목록 확인 (_workspace/02_developer_changes.md 또는 git diff)
2. 경계면 검증 5종 실행
3. 실행 테스트
4. 결과 보고서 작성
```

## 경계면 검증 5종

### V1. CLI ↔ MCP 미러링

**방법:** `cli/commands.py`의 `@cli.command()`/`@group.command()` 데코레이터와 `mcp_server.py`의 `@mcp.tool()` 데코레이터를 추출하여 1:1 대응을 확인한다.

```
확인 항목:
- CLI 커맨드에 대응하는 MCP 도구가 존재하는가
- 파라미터 이름/타입/기본값이 일치하는가
- 동일 입력에 의미적으로 동일한 결과를 반환하는가 (포맷 차이 허용)
```

### V2. DB 스키마 ↔ Repository

**방법:** `db/schema.py`의 CREATE TABLE 문에서 테이블명·컬럼명을 추출하고, `db/repository.py`의 SQL 문과 대조한다.

```
확인 항목:
- 새 테이블/컬럼이 schema.py에 정의되어 있는가
- repository.py의 SQL이 올바른 테이블명·컬럼명을 사용하는가
- INSERT/UPDATE 시 NOT NULL 컬럼에 값을 제공하는가
```

### V3. Analysis ↔ Repository 인터페이스

**방법:** analysis/ 모듈에서 `self.repo.xxx()` 호출을 추출하고, repository.py에 해당 메서드가 존재하는지 확인한다.

```
확인 항목:
- 호출되는 메서드가 Repository에 실제 존재하는가
- 인자 수와 타입이 일치하는가
- 반환값을 analysis 측이 올바르게 사용하는가
```

### V4. Import 체인

**방법:** 새로 추가/수정된 파일의 import 문을 추적하여 순환 참조를 확인한다.

```
확인 항목:
- 순환 import 없는가 (A → B → A)
- __init__.py에서 필요한 심볼을 export하는가
- 상대 import (.xxx)와 절대 import 혼용 없는가
```

### V5. config_patterns.yaml ↔ ConfigTracker

새 config 패턴이 추가된 경우에만 실행:
```
확인 항목:
- YAML 패턴의 필드명이 ConfigTracker가 기대하는 키와 일치하는가
- 정규표현식이 유효한가
```

## 실행 테스트

```bash
# 1. 기본 동작 확인
python -m cpp_analyzer --help

# 2. 새 커맨드의 --help
python -m cpp_analyzer {new_command} --help

# 3. 가능하면 예제로 실행
python -m cpp_analyzer index examples/ --db /tmp/test_qa.db
python -m cpp_analyzer {new_command} --db /tmp/test_qa.db {args}
```

## 보고서 형식

```markdown
# QA Report

## 변경 요약
- {변경 내용 1줄 요약}

## 검증 결과

| 항목 | 상태 | 비고 |
|------|------|------|
| V1. CLI↔MCP 미러링 | PASS/FAIL | {설명} |
| V2. DB↔Repository | PASS/FAIL | {설명} |
| V3. Analysis↔Repository | PASS/FAIL | {설명} |
| V4. Import 체인 | PASS/FAIL | {설명} |
| V5. Config 패턴 | PASS/SKIP | {설명} |
| 실행 테스트 | PASS/FAIL | {설명} |

## 발견된 문제
- [ ] {문제 설명} → {수정 제안}

## 테스트 로그
{실행 결과 붙여넣기}
```
