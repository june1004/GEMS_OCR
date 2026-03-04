# 영수증 OCR FE 연동 API 규격 (FE 개발사 전달용)

> FE 개발사 연동에 필요한 API만 포함.  
> Base URL·인증 등은 연동 환경에 따라 별도 협의.

---

## 1. Presigned URL 발급

**Method**: `POST`  
**URL**: `/api/v1/receipts/presigned-url`

**요청**  
Query 또는 Form (`application/x-www-form-urlencoded`)

| 파라미터    | 타입   | 필수 | 설명 |
|-------------|--------|------|------|
| fileName    | string | O    | 파일명 |
| contentType | string | O    | 예: `image/jpeg` |
| userUuid    | string | O    | 사용자 식별자 |
| type        | string | O    | `STAY` \| `TOUR` |
| receiptId   | string | X    | 같은 신청에 추가 업로드 시 기존 receiptId |

**응답 (200)**

```json
{
  "uploadUrl": "https://...",
  "receiptId": "uuid",
  "objectKey": "receipts/uuid_xxx.jpg"
}
```

- 첫 이미지 응답의 `receiptId`를 신청 ID로 보관.
- 추가 이미지는 동일 `receiptId`로 재호출 후 업로드.

---

## 2. 이미지 업로드

**Method**: `PUT`  
**URL**: 1번 응답의 `uploadUrl`

- Body: 이미지 바이너리.
- 각 이미지의 `objectKey`를 Complete 요청의 `documents[].imageKey`에 사용.

---

## 3. 검증 완료 (Complete)

**Method**: `POST`  
**URL**: `/api/v1/receipts/complete`  
**Content-Type**: `application/json`

**Request Body**

| 필드      | 타입   | 필수 | 설명 |
|-----------|--------|------|------|
| receiptId | string | O    | 1번에서 수신한 receiptId |
| userUuid  | string | O    | presigned 발급 시와 동일 |
| type      | string | O    | `STAY` \| `TOUR` |
| documents | array  | O    | 업로드한 이미지 목록 (3.1) |
| data      | object | X    | 사용자 입력. 전달 시 `items` 배열 사용 (3.2) |

**3.1 `documents`**

각 요소:

| 필드     | 타입   | 필수 | 설명 |
|----------|--------|------|------|
| imageKey | string | O    | 1번 응답의 objectKey |
| docType  | string | O    | `RECEIPT` \| `OTA_INVOICE` |

- STAY: RECEIPT 1개 필수, OTA_INVOICE 0~1개.
- TOUR: RECEIPT만 1~3개.
- `documents`와 `data.items`는 **동일 순서**로 전달 (`documents[i]` ↔ `data.items[i]`).

**3.2 `data` (선택)**

| 필드  | 타입  | 필수 | 설명 |
|-------|-------|------|------|
| items | array | data 사용 시 O | 장별 사용자 입력. `documents`와 같은 길이·순서. |

`data.items[]` 요소:

| 필드       | 타입   | 필수 | 설명 |
|------------|--------|------|------|
| amount     | number | O    | 사용자 입력 금액 |
| payDate    | string | O    | 결제일 (예: `YYYY-MM-DD`) |
| storeName  | string | X    | 상호 |
| location   | string | X    | 지역 (STAY 시) |
| cardPrefix | string | X    | 카드 앞 4자리 |

**요청 예시 (TOUR, 2장)**

```json
{
  "receiptId": "a1b2c3d4-...",
  "userUuid": "user-123",
  "type": "TOUR",
  "documents": [
    { "imageKey": "receipts/a1b2c3d4_img1.jpg", "docType": "RECEIPT" },
    { "imageKey": "receipts/a1b2c3d4_img2.jpg", "docType": "RECEIPT" }
  ],
  "data": {
    "items": [
      { "amount": 50000, "payDate": "2026-02-15", "storeName": "A식당" },
      { "amount": 70000, "payDate": "2026-02-15", "storeName": "B카페" }
    ]
  }
}
```

**요청 예시 (STAY, RECEIPT + OTA)**

```json
{
  "receiptId": "a1b2c3d4-...",
  "userUuid": "user-123",
  "type": "STAY",
  "documents": [
    { "imageKey": "receipts/a1b2c3d4_receipt.jpg", "docType": "RECEIPT" },
    { "imageKey": "receipts/a1b2c3d4_ota.jpg", "docType": "OTA_INVOICE" }
  ],
  "data": {
    "items": [
      { "amount": 120000, "payDate": "2026-02-20", "location": "강원도 춘천시", "cardPrefix": "1234" },
      { "amount": 120000, "payDate": "2026-02-20" }
    ]
  }
}
```

**응답 (200)**

```json
{
  "status": "PROCESSING",
  "receiptId": "a1b2c3d4-..."
}
```

- 최종 결과는 콜백 또는 4번 Status 조회로 수신.

---

## 4. 결과 조회 (Status)

**Method**: `GET`  
**URL**: `/api/v1/receipts/{receiptId}/status`

**응답 (200)**

| 필드                      | 타입    | 설명 |
|---------------------------|---------|------|
| submission_id             | string  | 신청 ID |
| project_type              | string  | `STAY` \| `TOUR` |
| overall_status            | string  | 신청 단위 최종 상태 |
| total_amount              | number  | FIT 항목 합산 금액 |
| global_fail_reason       | string \| null | 사유 |
| audit_trail               | string  | 판정 요약 |
| rewardAmount              | number  | 리워드 금액 |
| shouldPoll                | boolean | true 시 동일 URL 재조회 권장 |
| recommendedPollIntervalMs | number \| null | 권장 폴링 간격(ms) |
| reviewRequired            | boolean | 관리자 검토 대기 여부 |
| statusStage               | string  | `AUTO_PROCESSING` \| `MANUAL_REVIEW` \| `DONE` |
| items                     | array   | 장별 목록 (4.1) |

**4.1 `items[]`**

| 필드           | 타입   | 설명 |
|----------------|--------|------|
| item_id        | string | 장별 ID |
| status         | string | 해당 장 판정 |
| error_code     | string \| null | 장별 에러코드 |
| error_message  | string \| null | 에러 메시지(한글) |
| extracted_data | object \| null | OCR 결과 (store_name, amount, pay_date, address, card_num) |
| image_url      | string | 영수증 이미지 식별자 또는 URL |

---

## 8. 에러

- 4xx/5xx: JSON `{ "detail": "메시지" }`
- 409: receiptId type 불일치, 이미 완료된 신청 등.

---

## 9. API 목록

| 용도           | Method | URL |
|----------------|--------|-----|
| 업로드 URL     | POST   | /api/v1/receipts/presigned-url |
| 이미지 업로드  | PUT    | (presigned uploadUrl) |
| 검증 완료      | POST   | /api/v1/receipts/complete |
| 결과 조회      | GET    | /api/v1/receipts/{receiptId}/status |
