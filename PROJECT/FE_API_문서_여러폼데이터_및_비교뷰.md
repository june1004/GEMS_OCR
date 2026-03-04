# FE 연동 API 명세 — 여러 폼데이터(방식 2) + 폼데이터·OCR·영수증 이미지 나란히 비교

> **대상**: 프론트엔드 개발  
> **목적**: 영수증 여러 장에 대해 **장별 폼데이터** 전송 및, **FE 폼데이터 | OCR 데이터 | 영수증 이미지**를 나란히 비교해 보여줄 수 있는 응답 구조 정의.  
> (백엔드 구현 상세는 제외)

---

## 0. 개요

- **요청**: Complete 시 **`documents[]`** 와 **`data.items[]`** 를 **같은 순서**로 보냄. `data.items[i]`는 `documents[i]`에 대한 사용자 입력(금액·결제일 등).
- **응답**: 신청 단건 조회 시 **장별로** “FE 입력 · OCR 결과 · 이미지”를 매칭할 수 있도록 **같은 인덱스**로 묶어서 제공.

---

## 1. Presigned URL 발급

**Method**: `POST`  
**URL**: `/api/v1/receipts/presigned-url`

**요청 (Query 또는 Form)**

| 파라미터   | 타입   | 필수 | 설명 |
|------------|--------|------|------|
| fileName   | string | O    | 파일명 |
| contentType| string | O    | 예: `image/jpeg` |
| userUuid   | string | O    | 사용자 식별자 |
| type       | string | O    | `STAY` \| `TOUR` |
| receiptId  | string | X    | 같은 신청에 추가 업로드 시 기존 receiptId |

**응답 (200)**

```json
{
  "uploadUrl": "https://...",
  "receiptId": "uuid",
  "objectKey": "receipts/uuid_xxx.jpg"
}
```

- 첫 번째 이미지에서 받은 **receiptId**를 신청 ID로 저장.
- 추가 이미지는 **같은 receiptId**로 presigned 재발급 후 업로드.

---

## 2. 이미지 업로드

**Method**: `PUT`  
**URL**: (1번 응답의 `uploadUrl`)

- Body: 이미지 바이너리.
- 업로드한 각 이미지의 **objectKey**를 기록해 3번 Complete의 `documents[].imageKey`에 사용.

---

## 3. 검증 완료 요청 (Complete) — 여러 폼데이터(방식 2)

**Method**: `POST`  
**URL**: `/api/v1/receipts/complete`

**Request Body (JSON)**

| 필드       | 타입   | 필수 | 설명 |
|------------|--------|------|------|
| receiptId  | string | O    | 1번에서 받은 receiptId |
| userUuid   | string | O    | presigned 발급 시와 동일 |
| type       | string | O    | `STAY` \| `TOUR` |
| documents  | array  | O    | 업로드한 이미지 목록 (아래 3.1) |
| data       | object | X    | 사용자 입력(폼데이터). **방식 2**에서는 `items` 배열 사용 (아래 3.2) |

### 3.1 `documents` 배열

각 요소:

| 필드     | 타입   | 필수 | 설명 |
|----------|--------|------|------|
| imageKey | string | O    | 1번 응답의 objectKey |
| docType  | string | O    | `RECEIPT` \| `OTA_INVOICE` |

- **STAY**: RECEIPT 1개 필수, OTA_INVOICE 0~1개.
- **TOUR**: RECEIPT만 1~3개.
- **순서**: `data.items[]`와 **같은 순서**로 넣음. `documents[i]` ↔ `data.items[i]` 1:1 대응.

### 3.2 `data` (방식 2 — 장별 폼데이터)

`data`를 보낼 때 **`items`** 배열로 **장별** 사용자 입력을 전달.

| 필드  | 타입  | 필수 | 설명 |
|-------|-------|------|------|
| items | array | O    | `documents[]`와 **동일한 순서**. 길이 = documents 길이. |

**`data.items[]` 요소 (공통)**

| 필드        | 타입   | 필수 | 설명 |
|-------------|--------|------|------|
| amount      | number | O    | 사용자 입력 금액 |
| payDate     | string | O    | 결제일 (예: `YYYY-MM-DD`) |
| storeName   | string | X    | 상호 (TOUR 권장) |
| location    | string | X    | 지역 (STAY 시 사용) |
| cardPrefix  | string | X    | 카드 앞 4자리 |

- **STAY**: RECEIPT 1건 + OTA 0~1건 → `items` 길이 1 또는 2. OTA 항목은 금액 등 선택.
- **TOUR**: RECEIPT 1~3건 → `items` 길이 1~3. 각 장별 금액·결제일 등.

**Complete 요청 예시 (TOUR, 영수증 2장)**

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

**Complete 요청 예시 (STAY, RECEIPT + OTA 2장)**

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

**Response (200)**

```json
{
  "status": "PROCESSING",
  "receiptId": "a1b2c3d4-..."
}
```

- 이후 최종 결과는 **콜백** 또는 **4번 Status 조회**로 수신.

---

## 4. 결과 조회 (Status) — 사용자/일반

**Method**: `GET`  
**URL**: `/api/v1/receipts/{receiptId}/status`

**Response (200) — 공통**

| 필드                     | 타입    | 설명 |
|--------------------------|---------|------|
| submission_id            | string  | 신청 ID (receiptId와 동일) |
| project_type             | string  | `STAY` \| `TOUR` |
| overall_status           | string  | 신청 단위 최종 상태 |
| total_amount             | number  | FIT 항목 합산 금액 |
| global_fail_reason       | string \| null | 사유 |
| audit_trail              | string  | 판정 요약 |
| rewardAmount             | number  | 리워드 금액 |
| shouldPoll               | boolean | true면 재조회 권장 |
| recommendedPollIntervalMs| number \| null | 권장 폴링 간격(ms) |
| reviewRequired           | boolean | 관리자 검토 대기 여부 |
| statusStage              | string  | `AUTO_PROCESSING` \| `MANUAL_REVIEW` \| `DONE` |
| items                    | array   | **장별 목록** (아래 4.1) |

### 4.1 `items[]` — 장별 (OCR·이미지)

| 필드           | 타입   | 설명 |
|----------------|--------|------|
| item_id        | string | 장별 ID |
| status         | string | 해당 장 판정 (FIT / UNFIT_* / PENDING_* / ERROR_OCR 등) |
| error_code     | string \| null | 장별 에러코드 |
| error_message  | string \| null | 에러 메시지(한글) |
| extracted_data | object \| null | **OCR 결과**: store_name, amount, pay_date, address, card_num |
| image_url      | string | 영수증 이미지 식별자 또는 URL (이미지 노출용) |

- **나란히 비교 시**: 이 `items[]`는 **OCR 데이터**와 **영수증 이미지** 열에 사용.  
- **FE 폼데이터** 열은 **5번 관리자 상세**의 `user_input_snapshot.items[]`와 **인덱스**로 매칭.

---

## 5. 관리자 — 신청 단건 상세 (폼데이터·OCR·이미지 나란히 비교용)

**Method**: `GET`  
**URL**: `/api/v1/admin/submissions/{receiptId}`

**Response (200)** — FE 폼데이터 | OCR 데이터 | 영수증 이미지를 **같은 인덱스**로 나란히 보여줄 수 있는 구조.

### 5.1 최상위

| 필드           | 타입   | 설명 |
|----------------|--------|------|
| receiptId      | string | 신청 ID |
| submission     | object | 신청 메타 + **FE 입력 스냅샷** (아래 5.2) |
| statusPayload  | object | 판정·장별 OCR·이미지 (아래 5.3) |

### 5.2 `submission` — FE 입력 스냅샷 포함

| 필드                 | 타입   | 설명 |
|----------------------|--------|------|
| submission_id        | string | 신청 ID |
| user_uuid             | string | 사용자 식별자 |
| project_type          | string | `STAY` \| `TOUR` |
| status                | string | 최종 상태 |
| total_amount          | number | 합산 금액 |
| global_fail_reason    | string \| null | 사유 |
| audit_trail           | string | 판정 요약 |
| created_at            | string \| null | 생성 시각 (ISO 8601) |
| **user_input_snapshot** | object \| null | **Complete 시 FE가 보낸 `data`** (방식 2에서는 `items` 배열 포함) |

**`user_input_snapshot` (방식 2)**

| 필드   | 타입  | 설명 |
|--------|-------|------|
| items  | array | **장별 FE 폼데이터**. Complete의 `data.items[]`와 동일 순서. |

`user_input_snapshot.items[i]` 예:

```json
{
  "amount": 50000,
  "payDate": "2026-02-15",
  "storeName": "A식당",
  "location": null,
  "cardPrefix": "1234"
}
```

- Complete 시 `data`를 보내지 않았으면 `user_input_snapshot`은 `null`.

### 5.3 `statusPayload` — OCR·이미지

| 필드    | 타입  | 설명 |
|---------|-------|------|
| submission_id   | string | 신청 ID |
| overall_status | string | 신청 단위 상태 |
| total_amount   | number | 합산 금액 |
| items          | array  | **장별 OCR + 이미지** (아래 5.4) |
| audit_trail    | string | 판정 요약 |

### 5.4 `statusPayload.items[]` — 장별 OCR + 이미지

| 필드           | 타입   | 설명 |
|----------------|--------|------|
| item_id        | string | 장별 ID |
| status         | string | 해당 장 판정 |
| error_code     | string \| null | 장별 에러코드 |
| error_message  | string \| null | 에러 메시지 |
| extracted_data | object \| null | **OCR 결과** (store_name, amount, pay_date, address, card_num) |
| image_url      | string | **영수증 이미지** 식별자 또는 URL |

### 5.5 나란히 비교용 매칭 규칙

- **같은 인덱스**로 한 행 구성: `i = 0, 1, ...`
  - **FE 폼데이터**: `submission.user_input_snapshot.items[i]` (없으면 해당 행은 비움)
  - **OCR 데이터**: `statusPayload.items[i].extracted_data`
  - **영수증 이미지**: `statusPayload.items[i].image_url` (URL이 아니면 이미지 조회 API로 presigned URL 발급)

**예시 (TOUR 2장)**

| 인덱스 | FE 폼데이터 (user_input_snapshot.items[i]) | OCR 데이터 (statusPayload.items[i].extracted_data) | 영수증 이미지 (statusPayload.items[i].image_url) |
|--------|--------------------------------------------|-----------------------------------------------------|--------------------------------------------------|
| 0      | amount: 50000, payDate: 2026-02-15, storeName: A식당 | amount: 50000, pay_date: 2026-02-15, store_name: A식당 | (이미지 URL 또는 key) |
| 1      | amount: 70000, payDate: 2026-02-15, storeName: B카페 | amount: 70000, pay_date: 2026-02-15, store_name: B카페 | (이미지 URL 또는 key) |

---

## 6. 관리자 — 이미지 presigned URL (선택)

이미지 열에 **URL**이 필요할 때 사용.

**Method**: `GET`  
**URL**: `/api/v1/admin/receipts/{receiptId}/images`

**Response (200)**

```json
{
  "receiptId": "uuid",
  "expiresIn": 600,
  "items": [
    {
      "item_id": "uuid",
      "doc_type": "RECEIPT",
      "image_key": "receipts/...",
      "image_url": "https://...presigned..."
    }
  ]
}
```

- `items[]` 순서는 상세 조회의 `statusPayload.items[]`와 동일하게 유지.
- FE는 `item_id`로 매칭하거나 **순서**로 매칭해 나란히 비교 테이블의 이미지 열에 사용.

---

## 7. 관리자 — 수동 판정(검수 완료)

**Method**: `POST`  
**URL**: `/api/v1/admin/submissions/{receiptId}/override`

**Request Body (JSON)**

| 필드                  | 타입    | 필수 | 설명 |
|-----------------------|---------|------|------|
| status                | string  | O    | 최종 판정: `FIT` \| `UNFIT` 등 |
| reason                | string  | O    | 검수 사유 |
| override_reward_amount| number  | X    | 리워드 금액 (필요 시) |
| resend_callback       | boolean | X    | true면 FE로 콜백 재전송 |

**Response (200)**

```json
{
  "receiptId": "uuid",
  "previous_status": "PENDING_VERIFICATION",
  "new_status": "FIT",
  "updated_at": "2026-03-04T12:00:00"
}
```

---

## 8. 에러 응답

- **4xx/5xx**: JSON `{ "detail": "메시지" }`
- **409**: receiptId type 불일치, 이미 완료된 신청 등.

---

## 9. 요약

| 용도                     | API | 비고 |
|--------------------------|-----|------|
| 업로드 URL               | POST /api/v1/receipts/presigned-url | |
| 이미지 업로드            | PUT uploadUrl | |
| 검증 요청 (여러 폼데이터) | POST /api/v1/receipts/complete | Body에 `data.items[]` (documents와 동일 순서) |
| 결과 조회                | GET /api/v1/receipts/{receiptId}/status | items[] = OCR·이미지 |
| 나란히 비교 (관리자)     | GET /api/v1/admin/submissions/{receiptId} | user_input_snapshot.items[] + statusPayload.items[] + image_url |
| 이미지 URL (관리자)      | GET /api/v1/admin/receipts/{receiptId}/images | 선택 |
| 검수 완료 (관리자)       | POST /api/v1/admin/submissions/{receiptId}/override | |

- **방식 2**: Complete 시 **`data.items[]`** 로 장별 폼데이터 전송.
- **나란히 비교**: 관리자 상세 응답의 **`user_input_snapshot.items[i]`** · **`statusPayload.items[i]`** · **이미지**를 인덱스 `i`로 묶어 FE 폼데이터 | OCR 데이터 | 영수증 이미지 한 행으로 표시.
