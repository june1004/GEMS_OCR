# 검수 있는 경우 vs 없는 경우 — 프로세스·적용 API·BE 지원 현황

> 두 가지 연동 방식을 정확히 구분한 정리 문서.

---

## 1. 요약 비교표

| 구분 | 검수 없는 경우 | 검수 있는 경우 |
|------|----------------|----------------|
| **연동 방식** | documents-only (권장) | documents + data (폼 데이터) |
| **FE 전송** | `documents` 만 전송, `data` 미전송 | `documents` + `data`(금액·결제일·지역 등) 전송 |
| **판정 기준** | OCR 결과만으로 자동 판정 | OCR 우선, FE 입력과 비교 후 불일치 시 수동 검수 대기 |
| **관리자 검수** | 없음 (자동 판정만) | PENDING_VERIFICATION 등 시 관리자 검수 후 override |
| **현재 BE 지원** | ✅ 지원 | ✅ 지원 |
| **수정 필요** | 없음 | 선택 사항 (아래 4절 참고) |

---

## 2. 검수 없는 경우 (documents-only)

### 2.1 프로세스

1. **Presigned URL 발급**  
   FE → BE: 업로드할 파일 정보(fileName, contentType, userUuid, type) 전달 후 `uploadUrl`, `receiptId`, `objectKey` 수신.
2. **이미지 업로드**  
   FE → 스토리지: `uploadUrl`로 이미지 PUT. (추가 이미지 시 동일 `receiptId`로 presigned 재발급 후 업로드.)
3. **Complete (검증 요청)**  
   FE → BE: `receiptId`, `userUuid`, `type`, **`documents`만** 전송. **`data`는 보내지 않음.**
4. **BE 자동 처리**  
   OCR 수행 → OCR 결과만으로 FIT/UNFIT/ERROR 등 **자동 판정** → DB 저장.
5. **결과 수신**  
   - **콜백**: BE가 분석 완료 시 `OCR_RESULT_CALLBACK_URL`로 POST 1회.  
   - **폴링**: FE가 `GET /api/v1/receipts/{receiptId}/status` 반복 호출로 최종 상태 조회.

**관리자 검수 단계 없음.** 사용자 입력값과의 비교도 없음.

### 2.2 적용 API (순서)

| 단계 | API | 비고 |
|------|-----|------|
| 1 | `POST /api/v1/receipts/presigned-url` | uploadUrl, receiptId, objectKey 발급 |
| 2 | (S3/MinIO) PUT uploadUrl | FE → 스토리지 직접 업로드 |
| 3 | `POST /api/v1/receipts/complete` | Body: receiptId, userUuid, type, **documents** (data 없음) |
| 4 | `GET /api/v1/receipts/{receiptId}/status` | 폴링 또는 콜백 수신 후 최종 확인 |

### 2.3 현재 BE 지원 여부

- **✅ 적용 가능.**  
- Complete 시 `documents`만 있으면 되며, `data`는 없어도 됨.  
- 수정 불필요.

---

## 3. 검수 있는 경우 (documents + data)

### 3.1 프로세스

1. **Presigned URL 발급**  
   (검수 없는 경우와 동일)
2. **이미지 업로드**  
   (검수 없는 경우와 동일)
3. **Complete (검증 요청)**  
   FE → BE: `receiptId`, `userUuid`, `type`, **`documents`** 와 함께 **`data`**(사용자 입력 금액·결제일·지역 등) 전송.
4. **BE 처리 (OCR + 비교)**  
   - OCR 수행.  
   - **OCR 우선**: 신뢰도 높으면 OCR 값만 사용, 낮으면 FE `data`를 참조.  
   - **FE 입력 금액 vs OCR 금액**이 10% 이상 차이 → 해당 건 **PENDING_VERIFICATION**(수동 검증 대기).  
   - 그 외 규칙(지역·기간·중복 등)에 따라 FIT/UNFIT/PENDING_NEW 등 판정.
5. **결과 수신**  
   콜백 또는 status 조회로 FE에 전달. `status` / `items[].status` 에 PENDING_VERIFICATION 등 포함.
6. **관리자 검수**  
   - 관리자가 **PENDING_VERIFICATION**, **PENDING_NEW**, **UNFIT** 등 건을 조회.  
   - 상세 조회로 **OCR 기반 결과**(extracted_data, audit_trail, error_code 등) 확인.  
   - **Override** API로 **FIT/UNFIT 등 최종 판정** 입력 → 검수 완료.  
   - 필요 시 콜백 재전송.

### 3.2 적용 API (순서)

| 단계 | API | 비고 |
|------|-----|------|
| 1 | `POST /api/v1/receipts/presigned-url` | 동일 |
| 2 | (S3/MinIO) PUT uploadUrl | 동일 |
| 3 | `POST /api/v1/receipts/complete` | Body: receiptId, userUuid, type, **documents + data** |
| 4 | `GET /api/v1/receipts/{receiptId}/status` | FE 결과 수신·폴링 |
| 5 | `GET /api/v1/admin/submissions` | 관리자: 검수 대상 목록 조회 (status=PENDING_VERIFICATION 등) |
| 6 | `GET /api/v1/admin/submissions/{receiptId}` | 관리자: 단건 상세 (items[].extracted_data, ocr_raw, audit_trail 등) |
| 7 | `POST /api/v1/admin/submissions/{receiptId}/override` | 관리자: 최종 판정(FIT/UNFIT 등) + reason, 선택 시 resend_callback |

### 3.3 현재 BE 지원 여부

- **✅ 둘 다 적용 가능.**  
  - **검수 없는 흐름**: documents-only로 그대로 사용.  
  - **검수 있는 흐름**: Complete에 `data` 포함 시 금액 불일치 → PENDING_VERIFICATION 처리되고, 관리자는 기존 admin API(목록/상세/override)로 검수 완료 가능.  
- **단, FE가 보낸 `data`(사용자 입력값)는 현재 DB에 저장하지 않음.**  
  - 관리자 상세 조회 응답에는 **OCR 결과**(extracted_data, receipt_items 테이블 값)와 **audit_trail**, **error_code** 등만 포함됨.  
  - “사용자가 입력한 금액/결제일”을 관리자 화면에 **나란히** 보여주려면 아래 4절과 같은 수정이 필요함.

---

## 4. 수정이 필요한지 여부

### 4.1 검수 없는 경우 (documents-only)

- **수정 없음.**  
  현재 BE로 그대로 운영 가능.

### 4.2 검수 있는 경우 (documents + data)

- **기본 동작**: **수정 없이도 적용 가능.**  
  - OCR vs FE 입력 비교 → PENDING_VERIFICATION → 관리자 override까지 모두 구현됨.  
  - 관리자는 **OCR 기반 결과**(extracted_data, audit_trail, error_code)만으로도 검수 가능.

- **선택적 수정 (관리자 UX 강화)**  
  “관리자가 **FE가 보낸 입력값**과 **OCR 결과**를 **나란히 비교**해서 검수하고 싶다”면 다음이 필요함.  
  - **저장**: Complete 수신 시 `data`(또는 amount, payDate, location 등 필요한 필드)를 DB에 저장.  
    - 예: `submissions` 테이블에 `user_input_snapshot` (JSONB) 추가 또는 별도 테이블.  
  - **노출**: `GET /api/v1/admin/submissions/{receiptId}` 응답에 “FE 제출 시 사용자 입력값” 필드 추가.  
  - 그러면 관리자 웹에서 “사용자 입력 금액 vs OCR 금액” 등을 나란히 보여줄 수 있음.  
  - **현재는 이 필드가 없으므로**, 관리자 화면에는 OCR 결과·audit_trail·에러 사유만 표시됨.

---

## 5. 정리

| 항목 | 검수 없는 경우 | 검수 있는 경우 |
|------|----------------|----------------|
| **프로세스** | Presigned → 업로드 → Complete(documents만) → 자동 판정 → 콜백/status | Presigned → 업로드 → Complete(documents+data) → OCR·비교(OCR 우선) → 불일치 시 PENDING_VERIFICATION → 관리자 상세 조회 → override로 검수 완료 |
| **적용 API** | presigned-url, PUT 업로드, complete, status | 위 + admin submissions 목록/상세, admin override |
| **BE 둘 다 지원 여부** | ✅ 지원 | ✅ 지원 |
| **수정 필요** | 없음 | 없음 (선택: 관리자 화면에 FE 입력값 노출 시 Complete 시 data 저장·상세 API 확장) |

현재 BE는 **검수 없는 흐름(documents-only)** 과 **검수 있는 흐름(documents+data + 관리자 override)** **둘 다** 적용 가능하며, 추가로 “관리자 화면에서 FE 입력값과 OCR을 나란히 비교”하려는 경우에만 저장·API 확장 수정을 고려하면 됩니다.
