# FE 폼데이터 요청·응답 흐름 + 여러 폼데이터 수신 조건 정리

> [GEMS OCR API - Complete](https://api.nanum.online/docs#/FE%20-%20Step%203%3A%20Complete/submit_receipt_api_v1_receipts_complete_post) 기준.  
> **FE가 폼데이터를 보내고 응답을 받는 구조**와, **여러 폼데이터를 받는 조건**으로 정리.

---

## 1. 흐름 정리: FE 폼데이터 요청 → 응답

**맞습니다. FE가 폼데이터를 담아 요청하고, BE가 응답을 돌려줘야 하는 구조입니다.**

| 단계 | 주체 | 내용 |
|------|------|------|
| 요청 | **FE** | `POST /api/v1/receipts/complete` 호출 시 **Body에 `documents` + `data`(폼데이터)** 를 담아 전송. |
| 응답 | **BE** | `{ "status": "PROCESSING", "receiptId": "uuid" }` 등으로 **즉시 응답**. 이후 OCR·판정은 비동기이며, 최종 결과는 콜백 또는 `GET /api/v1/receipts/{receiptId}/status` 로 수신. |

- **요청**: FE → BE (폼데이터 포함 Complete 요청)  
- **응답**: BE → FE (status, receiptId 등)  
- **검수 있는 구조**에서는 FE가 사용자가 입력한 금액·결제일·지역 등을 `data`에 넣어 보내고, BE는 그걸 받아 OCR 결과와 비교(OCR 우선)한 뒤, 불일치 시 수동 검수 대기(PENDING_VERIFICATION)로 두는 흐름입니다.

---

## 2. 현재 적용 여부 (api.nanum.online 기준)

**지금 노출된 메인 Complete API는 documents만 받고, 폼데이터(`data`) 수신이 들어가 있지 않은 상태로 보입니다.**

- **현재**
  - `POST /api/v1/receipts/complete`  
    - Request body: **`receiptId`, `userUuid`, `type`, `documents`** 만 사용 (documents-only).  
    - **`data` 필드는 스키마에 없거나 사용하지 않음** → 폼데이터를 받지 않음.
- **검수 있는 구조를 쓰려면**
  - **옵션 A**: 같은 URL에서 **Request body에 optional `data`** 를 추가해, FE가 폼데이터를 넣어 보낼 수 있게 한다.  
  - **옵션 B**: 폼데이터를 받는 전용 엔드포인트(예: `complete-legacy`)를 공개하고, FE는 검수 있는 구조일 때만 그쪽을 호출한다.

즉, **“FE가 폼데이터를 보내고 응답을 받는” 구조로 쓰려면, 서버에 폼데이터(`data`) 수신이 적용되어 있어야 하고, 현재는 그 적용이 안 되어 있는 상태**로 이해하면 됩니다.

---

## 3. “여러 폼데이터를 받는다”는 조건으로 정리

영수증이 **여러 장**인 경우(TOUR 1~3장, STAY 1+OTA 등)를 전제로, **여러 폼데이터를 받는** 방식을 두 가지로 나눕니다.

---

### 3.1 방식 1: 신청 1건당 하나의 `data` (현재 스키마)

- **의미**: 영수증이 여러 장이어도 **신청(submission) 단위로 하나의 `data` 객체**만 전달.
- **STAY**
  - `data`: 1건 (숙박 1건 + OTA 명세서 0~1장).
  - 필드 예: `amount`, `payDate`, `location`, `receiptImageKey`, `otaStatementKey` 등.
- **TOUR**
  - `data`: 1건 (관광 1건, 영수증 1~3장에 대한 **합산/대표 정보**).
  - 필드 예: `amount`(사용자 입력 합산 또는 대표 금액), `payDate`, `storeName`, **`receiptImageKeys`**(최대 3개 이미지 키 배열).

**요청 예 (TOUR, 영수증 2장)**

```json
{
  "receiptId": "uuid",
  "userUuid": "user-123",
  "type": "TOUR",
  "documents": [
    { "imageKey": "receipts/uuid_a.jpg", "docType": "RECEIPT" },
    { "imageKey": "receipts/uuid_b.jpg", "docType": "RECEIPT" }
  ],
  "data": {
    "storeName": "강원감자옹심이",
    "payDate": "2026-02-15",
    "amount": 120000,
    "cardPrefix": "1234",
    "receiptImageKeys": ["receipts/uuid_a.jpg", "receipts/uuid_b.jpg"]
  }
}
```

- **“여러 폼데이터”**:  
  - **이미지**는 여러 개(`documents[]`, `receiptImageKeys[]`)로 넘어오고,  
  - **사용자 입력**은 **1건의 `data`** (TOUR은 합산 금액 등)로 한 번에 받는 형태입니다.

---

### 3.2 방식 2: 장별로 폼데이터 배열을 받는 확장 (여러 건의 폼데이터)

- **의미**: 영수증 **장별로** 사용자 입력을 구분해 받고 싶을 때, **`data`를 배열 또는 장별 객체**로 확장.
- **예시 구조 (제안)**

  - **장별 배열**
    - `data.items`: `documents[]` 순서와 1:1 매칭되는 폼데이터 배열.
  - 예: TOUR 2장이면  
    `data.items[0]` = 1장째 금액·결제일,  
    `data.items[1]` = 2장째 금액·결제일.

**요청 예 (TOUR, 영수증 2장 – 장별 폼데이터)**

```json
{
  "receiptId": "uuid",
  "userUuid": "user-123",
  "type": "TOUR",
  "documents": [
    { "imageKey": "receipts/uuid_a.jpg", "docType": "RECEIPT" },
    { "imageKey": "receipts/uuid_b.jpg", "docType": "RECEIPT" }
  ],
  "data": {
    "items": [
      { "amount": 50000, "payDate": "2026-02-15", "storeName": "A상호" },
      { "amount": 70000, "payDate": "2026-02-15", "storeName": "B상호" }
    ]
  }
}
```

- **“여러 폼데이터를 받는다”**:  
  - **이미지 여러 장**에 대해 **폼데이터도 여러 건(`data.items[]`)** 으로 받는 조건으로 정의하는 방식입니다.  
- 이렇게 하려면 **API 스키마와 BE 로직**에서 `data.items[]` (또는 동등한 배열/객체)를 추가로 정의·처리해야 합니다.

---

## 4. 적용 시 권장 사항 (여러 폼데이터 조건 포함)

1. **메인 Complete API에 폼데이터 수신 적용**
   - `POST /api/v1/receipts/complete` Request body에 **optional `data`** 추가.
   - 우선 **방식 1**(신청 1건당 하나의 `data`)로 받고, BE는 기존처럼 `data`가 있으면 OCR와 비교·PENDING_VERIFICATION 처리.

2. **“여러 폼데이터”를 장별로 받고 싶을 때**
   - **방식 2**를 쓰려면:
     - Request body에 `data.items`(또는 `data` 배열) 스키마를 정의하고,
     - BE에서 `documents[]`와 `data.items[]`를 순서대로 매칭해 장별 금액·날짜 비교 로직을 태우면 됩니다.
   - 문서/스펙에 **“영수증 여러 장일 때, 장별 폼데이터 배열을 받는 경우”** 조건을 위와 같이 명시해 두는 것을 권장합니다.

3. **응답**
   - 폼데이터 수신 여부와 관계없이, Complete 호출에 대한 **응답은 동일**하게 유지하면 됩니다.  
     - `{ "status": "PROCESSING", "receiptId": "uuid" }`  
   - FE는 이 응답을 받은 뒤, 동일하게 status 폴링 또는 콜백으로 최종 결과를 받습니다.

---

## 5. 요약

| 항목 | 내용 |
|------|------|
| **FE 폼데이터 요청·응답** | FE가 **요청 Body에 폼데이터(`data`)를 담아** `POST /api/v1/receipts/complete` 호출 → BE가 **같은 요청에 대해 즉시 응답**(status, receiptId)을 반환. 검수 있는 구조에서는 이렇게 동작해야 함. |
| **현재 적용 여부** | 메인 Complete API는 documents만 받고 있어, **폼데이터 수신은 아직 적용되지 않은 상태**로 보임. optional `data` 추가 또는 legacy 엔드포인트 사용이 필요. |
| **여러 폼데이터** | **(1) 신청 1건당 하나의 `data`**: 여러 장이어도 하나의 `data`(TOUR은 `receiptImageKeys`·합산 금액 등)로 받음. **(2) 장별 여러 폼데이터**: `data.items[]`처럼 **배열로 여러 건** 받도록 스키마·로직 확장 후, `documents[]`와 1:1 매칭해 비교. |

이렇게 정리하면, **FE가 폼데이터를 보내고 응답을 받는지**에 대한 답과, **여러 폼데이터를 받는 조건**을 동시에 설명할 수 있습니다.
