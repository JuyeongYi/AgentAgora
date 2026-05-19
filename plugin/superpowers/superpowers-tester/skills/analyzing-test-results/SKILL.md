---
name: analyzing-test-results
description: Use when a test run produces failures - classify each failure and decide whether the implementer can fix it inline or it needs the debugger
model: opus
effort: high
delegation-target: "sp-implementer"
delegation-schema: "delegation_request"
---

# Analyzing Test Results

## Overview

테스트 실패는 종류가 다르다. 분류 없이 무작정 디버거로 넘기면 디버거가 과부하되고, 무작정 구현자에게 넘기면 구조적 문제가 패치로 가려진다. 이 스킬은 실패를 분류하고 다음 행선지를 정한다.

## 실패 분류

각 실패를 네 범주 중 하나로 판정한다:

1. **실제 버그** — 구현 코드가 명세대로 동작하지 않는다. 재현 가능하고 결정적.
2. **잘못된 테스트** — 테스트 자체가 틀렸다 (잘못된 기대값, 잘못된 셋업). 구현이 아니라 테스트를 고친다.
3. **플래키** — 같은 코드에서 통과·실패가 갈린다. 타이밍·순서·격리 문제.
4. **환경 요인** — 의존성 누락, 경로, 권한 등 코드 외부 원인.

## 행선지 결정

- **잘못된 테스트** → 테스터 자신이 테스트를 수정한다 (위임 없음).
- **단순한 실제 버그** (원인이 명확하고 국소적) → 구현자에게 `type=reply`로 반려, 실패 테스트·기대 동작·원인 추정을 포함.
- **원인 불명·구조적 실제 버그**, 또는 **플래키** → 디버거에게 `agora.dispatch` `type=task`로 위임. 에러·재현 절차·시도한 것을 포함.
- **환경 요인** → 구현자에게 보고하되 코드 문제 아님을 명시.

## 출력 규약

분석 결과는 항상 분류와 근거를 함께 적는다. "테스트 3건 실패"가 아니라 "테스트 3건 — 2건 실제 버그(단순, 구현자), 1건 플래키(디버거)"처럼 행선지까지 명시한다.

## 검증

`superpowers:verification-before-completion`을 따른다 — 실패를 분류했다고 주장하기 전에 실제 테스트 출력을 확인한다.
