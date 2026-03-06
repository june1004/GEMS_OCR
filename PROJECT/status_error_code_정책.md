# status / error_code / error_message 정리

> 제출(Submission)·장별(ReceiptItem) **status**, **error_code**, **error_message** 값·의미·관계를 한 문서로 정리한 참조용 문서입니다.

---

## 1. 적용 단위

| 구분 | 적용 대상 | 설명 |
|------|-----------|------|
| **Submission** | 1건의 신청(영수증 여러 장 가능) | `submissions.status`, `submissions.fail_reason` |
| **ReceiptItem** | 신청 내 1장의 영수증/증빙 | `receipt_items.status`, `receipt_items.error_code`, `receipt_items.error_message` |

- API의 **overall_status** = Submission의 `status`
- API의 **items[].status / error_code / error_message** = ReceiptItem 값

---

## 2. Submission(전체) status

| status | 의미 | 비고 |
|--------|------|------|
| **PENDING** | 업로드 대기, Complete 미호출 | |
| **PROCESSING** | OCR·자동 검증 진행 중 | |
| **VERIFYING** | 검수 대기(수동 검토 필요) | PENDING_VERIFICATION 등 |
| **FIT** | 적합, 리워드 지급 대상 | |
| **UNFIT** | 부적합 | 사유는 `fail_reason` 또는 장별 error_code 참고 |
| **ERROR** | 오류(OCR 실패·타임아웃 등) | |

---

## 3. ReceiptItem(장별) status

| status | 의미 | error_code 예 |
|--------|------|----------------|
| **PENDING** | 미판정(초기 또는 검증 전) | (없음) |
| **FIT** | 해당 장 적합 | (없음) |
| **UNFIT** | 해당 장 부적합(일반) | BIZ_003, BIZ_005, BIZ_006, BIZ_007, BIZ_010 등 |
| **UNFIT_CATEGORY** | 제외 업종 | BIZ_008, UNFIT_CATEGORY |
| **UNFIT_REGION** | 지역 불일치 | BIZ_004, UNFIT_REGION |
| **UNFIT_DATE** | 기간/날짜 불일치 | BIZ_002, OCR_002, UNFIT_DATE |
| **UNFIT_DUPLICATE** | 중복 제출 | BIZ_001, UNFIT_DUPLICATE |
| **PENDING_NEW** | 신규 상점 검수 대기 | PENDING_NEW |
| **PENDING_VERIFICATION** | 사용자 입력–OCR 불일치·인식 불량 검수 대기 | PENDING_VERIFICATION, OCR_004 |
| **ERROR_OCR** | 영수증 판독 불가 | OCR_001, ERROR_OCR |

---

## 4. error_code → status / error_message 매핑

**규칙**: `error_code` 하나로 **status**와 **error_message**가 결정됨. (BE: `_status_for_code`, `_fail_message`)

### 4.1 BIZ_* (업무 규칙)

| error_code | status | error_message (한글) |
|------------|--------|----------------------|
| BIZ_001 | UNFIT_DUPLICATE | BIZ_001 (중복 등록) |
| BIZ_002 | UNFIT_DATE | BIZ_002 (2026년 결제일 아님. 이벤트 기간 외 또는 2026년 이전인 경우) |
| BIZ_003 | UNFIT | BIZ_003 (최소 금액 미달) |
| BIZ_004 | UNFIT_REGION | BIZ_004 (강원특별자치도 외 지역) |
| BIZ_005 | UNFIT | BIZ_005 (캠페인 기간 아님) |
| BIZ_006 | UNFIT | BIZ_006 (캠페인 대상 지역 아님) |
| BIZ_007 | UNFIT | BIZ_007 (입력 금액과 OCR 금액 불일치) |
| BIZ_008 | UNFIT_CATEGORY | BIZ_008 (유흥업소 등 부적격 업종) |
| BIZ_010 | UNFIT | BIZ_010 (문서 구성 요건 불충족) |
| BIZ_011 | UNFIT | BIZ_011 (영수증/증빙 금액 불일치) |

### 4.2 OCR_* (인식·판독)

| error_code | status | error_message (한글) |
|------------|--------|----------------------|
| OCR_001 | ERROR_OCR | OCR_001 (영수증 판독 불가) |
| OCR_002 | UNFIT_DATE | OCR_002 (결제일 형식 오류) |
| OCR_003 | UNFIT | OCR_003 (마스터 상호 미등록) |
| OCR_004 | PENDING_VERIFICATION | OCR_004 (인식 불량·수동 검수 보정) |

### 4.3 검수·유형 구분용 (문자열 코드)

| error_code | status | error_message (한글) |
|------------|--------|----------------------|
| PENDING_NEW | PENDING_NEW | PENDING_NEW (신규 상점 검수 대기). 기본 정책은 자동 상점추가(AUTO_REGISTER) → 해당 시 FIT·데이터 자산화 |
| PENDING_VERIFICATION | PENDING_VERIFICATION | PENDING_VERIFICATION (사용자 입력값- OCR 불일치) |
| UNFIT_CATEGORY | UNFIT_CATEGORY | UNFIT_CATEGORY (제외 업종) |
| UNFIT_REGION | UNFIT_REGION | UNFIT_REGION (지역 불일치) |
| UNFIT_DATE | UNFIT_DATE | UNFIT_DATE (기간/날짜 불일치) |
| UNFIT_DUPLICATE | UNFIT_DUPLICATE | UNFIT_DUPLICATE (중복 제출) |
| ERROR_OCR | ERROR_OCR | ERROR_OCR (판독 불가) |

---

## 5. Submission fail_reason (전체 사유)

전체 건이 UNFIT/ERROR일 때 API·관리자에 노출되는 **fail_reason**은 아래처럼 정리된 문구로 매핑됨. (`_global_fail_reason`)

| error_code | fail_reason (요약) |
|------------|---------------------|
| BIZ_003 | UNFIT_TOTAL_AMOUNT (BIZ_003, 합산 금액 미달) |
| BIZ_011 | UNFIT_STAY_MISMATCH (BIZ_011, 숙박-증빙 불일치) |
| BIZ_004 | UNFIT_REGION (BIZ_004, 지역 불일치) |
| BIZ_002 | UNFIT_DATE (BIZ_002, 결제일/기간 오류) |
| PENDING_NEW | PENDING_NEW (신규 상점 확인 필요) |
| PENDING_VERIFICATION | PENDING_VERIFICATION (입력값- OCR 불일치) |
| UNFIT_CATEGORY | UNFIT_CATEGORY (제외 업종) |
| UNFIT_DUPLICATE | UNFIT_DUPLICATE (중복 제출) |
| ERROR_OCR | ERROR_OCR (판독 불가) |
| 그 외 | 위 매핑 없으면 `_fail_message(code)` 와 동일 문구 사용 |

---

## 6. API 응답에서의 사용

- **GET /api/v1/receipts/{receiptId}/status**  
  - `overall_status`: Submission `status`  
  - `items[].status`, `items[].errorCode`, `items[].errorMessage`: ReceiptItem 값 (장별)
- **콜백 POST body**  
  - 동일하게 `overall_status` + `items[]` 내 status/errorCode/errorMessage
- **관리자 API**  
  - Submission 상세: `status`, `fail_reason`  
  - ReceiptItem 목록: `status`, `error_code`, `error_message`

---

## 7. 구현 원칙 (에러·불일치 방지)

- **단일 소스**: 장별 판정은 **error_code 하나**만 두고, status·error_message는 그 코드에서 **파생**.
- **헬퍼**: `_resolve_item_status_error(code)` → `(status, error_code, error_message)` 로 항상 동시 설정.
- **호출**: item 판정 시 `mark_item(i, code)` 만 사용. (code=`None` → FIT)
- **추가 코드**: 새 사유는 **ErrorCode** enum + **\_fail_message** + **\_status_for_code** 에만 추가하면 됨.

이렇게 하면 status / error_code / error_message 가 서로 어긋나거나 메시지가 비는 경우를 줄일 수 있다.
