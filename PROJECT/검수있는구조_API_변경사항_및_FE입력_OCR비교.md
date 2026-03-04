# 검수 있는 구조 적용 시 API 변경 사항 + 관리자 FE 입력값·OCR 나란히 비교 기능

> 검수 있는 구조(documents+data) 적용 시 **변경되는 API·유지되는 API**와, **관리자 화면에서 FE 입력값과 OCR을 나란히 비교**하기 위한 **추가 변경**까지 정리한 문서.

---

## 1. 검수 있는 구조 적용 시 API 요약

| 구분 | API | 변경 여부 | 비고 |
|------|-----|-----------|------|
| FE 연동 | `POST /api/v1/receipts/presigned-url` | **변경 없음** | 그대로 사용 |
| FE 연동 | (스토리지) PUT uploadUrl | **변경 없음** | 그대로 사용 |
| FE 연동 | `POST /api/v1/receipts/complete` | **요청만 활용 방식 변경** | 검수 있는 구조 시 Body에 `data` 필요. 현재는 `complete-legacy`가 `data` 수신 가능. 메인 complete를 확장해 optional `data`를 받도록 할 수 있음. |
| FE 연동 | `GET /api/v1/receipts/{receiptId}/status` | **변경 없음** | 그대로 사용 |
| 관리자 | `GET /api/v1/admin/submissions` | **변경 없음** | 그대로 사용 |
| 관리자 | `GET /api/v1/admin/submissions/{receiptId}` | **응답 확장** | FE 입력값 비교 기능 적용 시 아래 2절 참고 |
| 관리자 | `POST /api/v1/admin/submissions/{receiptId}/override` | **변경 없음** | 그대로 사용 |
| 관리자 | `GET /api/v1/admin/receipts/{receiptId}/images` | **변경 없음** | 그대로 사용 |

**정리**: 검수 있는 구조로 “적용”한다는 것은 **Complete 호출 시 `data`를 채워 보내는 것**이므로, **별도 새 API를 만드는 것은 아님**.  
- 현재 BE: **`POST /api/v1/receipts/complete`** 는 documents-only(CompleteRequestV2)만 받고, **`POST /api/v1/receipts/complete-legacy`** 가 `data` 포함 요청(CompleteRequest)을 받음.  
- 따라서 검수 있는 구조 적용 시 **FE는 `complete-legacy`를 사용**하거나, **메인 complete API를 확장해 optional `data`를 받도록** 변경하면 됨. (스키마는 이미 CompleteRequest에 `data` 필드 있음.)  
**추가로** “관리자 화면에서 FE 입력값과 OCR을 나란히 비교”하려면 **한 가지 API 응답 확장**과 **BE/DB 수정**이 필요함(아래 2절).

---

## 2. 관리자 화면 “FE 입력값 vs OCR 나란히 비교” 기능 — 필요한 변경

현재 Complete 시 FE가 보낸 `data`는 **DB에 저장되지 않아** 관리자 상세 조회에서 노출할 수 없음.  
아래 변경을 하면 관리자 화면에서 **FE 입력값**과 **OCR 결과**를 나란히 비교할 수 있음.

---

### 2.1 DB 스키마 변경

**목적**: Complete 시 FE가 보낸 `data`(사용자 입력 스냅샷)를 저장.

| 항목 | 내용 |
|------|------|
| 테이블 | `submissions` |
| 추가 컬럼 | `user_input_snapshot` `JSONB` `NULL` 허용 |
| 의미 | Complete 요청 시 `data`가 있으면 그대로 저장. type별로 STAY/Tour 스키마(예: amount, payDate, location, receiptImageKey 등)가 JSON으로 들어감. |

**마이그레이션 예시 (SQL)**

```sql
-- submissions 테이블에 FE 제출 시 사용자 입력 스냅샷 저장 (검수 시 비교용)
ALTER TABLE submissions
ADD COLUMN IF NOT EXISTS user_input_snapshot JSONB;
```

---

### 2.2 BE 로직 변경

| 위치 | 변경 내용 |
|------|-----------|
| **Complete 처리** | `POST /api/v1/receipts/complete` 처리 시, `req.data`가 있으면 `submission.user_input_snapshot = req.data.model_dump()` (또는 JSON 직렬화) 로 저장 후 commit. (analyze_receipt_task 내부에서 submission을 갱신할 수 있으므로, Complete 핸들러에서 submission 한 번 읽은 뒤 저장하거나, task 진입 직후에 저장해 두면 됨.) |
| **관리자 상세 API** | `GET /api/v1/admin/submissions/{receiptId}` 응답에 **FE 입력 스냅샷** 포함. |

`req.data`는 이미 `StayData` 또는 `TourData`로 파싱되어 있으므로, `model_dump()` 또는 `dict()`로 JSON 저장 가능.  
저장 시점은 **analyze_receipt_task 시작 시** submission 레코드에 `user_input_snapshot`을 세팅하고 commit하는 방식이 무난함 (Complete 동기 응답에서는 이미 PROCESSING으로 돌입한 뒤이므로, task 내부에서 저장해도 됨).

---

### 2.3 API 응답 변경 — `GET /api/v1/admin/submissions/{receiptId}`

**현재 응답 구조**

```json
{
  "receiptId": "uuid",
  "submission": {
    "submission_id": "...",
    "user_uuid": "...",
    "project_type": "STAY" | "TOUR",
    "campaign_id": 1,
    "status": "...",
    "total_amount": 0,
    "global_fail_reason": null,
    "fail_reason": null,
    "audit_trail": "...",
    "created_at": "..."
  },
  "statusPayload": {
    "submission_id": "...",
    "project_type": "...",
    "overall_status": "...",
    "total_amount": 0,
    "items": [
      {
        "item_id": "...",
        "status": "...",
        "error_code": null,
        "error_message": null,
        "extracted_data": { "store_name": "...", "amount": 0, "pay_date": "...", "address": "...", "card_num": "..." },
        "image_url": "...",
        "ocr_raw": { ... }
      }
    ],
    "audit_trail": "...",
    ...
  }
}
```

**추가 필드 (FE 입력값 vs OCR 비교용)**

- `submission` 객체에 아래 필드 **추가** (기존 필드와 동일 레벨).

| 필드 | 타입 | 설명 |
|------|------|------|
| `user_input_snapshot` | `object` \| `null` | Complete 시 FE가 보낸 `data` 그대로. 없으면 `null`. |

**STAY 예시 (user_input_snapshot)**

```json
{
  "location": "강원도 춘천시",
  "payDate": "2026-02-15",
  "amount": 75000,
  "cardPrefix": "1234",
  "receiptImageKey": "receipts/uuid_a.jpg",
  "isOta": true,
  "otaStatementKey": "receipts/uuid_b.jpg"
}
```

**TOUR 예시 (user_input_snapshot)**

```json
{
  "storeName": "강원감자옹심이",
  "payDate": "2026-02-15",
  "amount": 120000,
  "cardPrefix": "1234",
  "receiptImageKeys": ["receipts/uuid_a.jpg", "receipts/uuid_b.jpg"]
}
```

이렇게 하면 관리자 화면에서:
- **FE 입력**: `statusPayload`가 아닌 `submission.user_input_snapshot` 참고 (금액·결제일·지역 등).
- **OCR 결과**: `statusPayload.items[].extracted_data`, `items[].ocr_raw` 참고.
- **장별 비교**: TOUR은 `receiptImageKeys` 순서와 `items[]` 순서를 매칭해, 장별로 FE 입력(합산 또는 1장일 때 amount) vs `extracted_data.amount` 비교 가능.

---

### 2.4 관리자 화면 (FE) 사용 방법 — “나란히 비교”

1. **단건 상세 조회**  
   `GET /api/v1/admin/submissions/{receiptId}` 호출.

2. **FE 입력값**  
   `response.submission.user_input_snapshot` 사용.  
   - STAY: `amount`, `payDate`, `location` 등.  
   - TOUR: `amount`(사용자 입력 합산 또는 1장 기준), `payDate`, `storeName`, `receiptImageKeys` 등.

3. **OCR 결과**  
   `response.statusPayload.items[]` 사용.  
   - 각 `item`의 `extracted_data`: `amount`, `pay_date`, `store_name`, `address`, `card_num`.  
   - `image_url`(또는 image_key)로 `user_input_snapshot`의 imageKey와 매칭 가능.  
   - 필요 시 `item.ocr_raw`로 원문 확인.

4. **나란히 표시**  
   - 테이블/카드 형태로 한 행에 “FE 입력(금액/결제일/지역 등)” 컬럼과 “OCR(금액/결제일/주소 등)” 컬럼을 나란히 두고,  
   - `user_input_snapshot`과 `items[].extracted_data`(및 필요 시 `items[].ocr_raw`)를 같은 장 단위로 매칭해 표시.

5. **검수 완료**  
   비교 확인 후 기존처럼 `POST /api/v1/admin/submissions/{receiptId}/override` 로 최종 판정(FIT/UNFIT 등) 호출.

---

## 3. 변경 사항 요약표

| 구분 | 변경 여부 | 내용 |
|------|-----------|------|
| **API 계약** | Complete | **변경 없음**. 기존 스키마에 `data` 필드 이미 있음. 검수 있는 구조는 이 필드를 채워 보내면 됨. |
| **API 계약** | admin 상세 | **응답 확장**. `submission.user_input_snapshot` 추가 (object \| null). |
| **DB** | submissions | **컬럼 추가**. `user_input_snapshot` JSONB nullable. |
| **BE** | Complete 처리 | **로직 추가**. `req.data` 존재 시 `submission.user_input_snapshot`에 저장. |
| **BE** | admin 상세 | **로직 추가**. 응답 `submission`에 `user_input_snapshot` 포함. |
| **관리자 FE** | 상세 화면 | **구현 추가**. `user_input_snapshot` vs `statusPayload.items[].extracted_data` 나란히 표시. |

---

## 4. 정리

- **검수 있는 구조만 적용**할 때:  
  - **API 스키마 변경 없음.**  
  - FE는 기존 Complete API에 `data`까지 넣어 호출하면 되고, 관리자는 기존 admin API로 검수 가능.

- **“관리자 화면에서 FE 입력값과 OCR을 나란히 비교”**까지 적용할 때:  
  - **변경되는 API**: **1개** — `GET /api/v1/admin/submissions/{receiptId}` 응답에 `submission.user_input_snapshot` 추가.  
  - **추가 필요**: DB 컬럼 1개, BE에서 Complete 시 `data` 저장 + admin 상세 시 `user_input_snapshot` 반환, 관리자 FE에서 위 스냅샷과 `statusPayload.items`를 매칭해 비교 UI 구현.

이 문서에 따라 적용하면 검수 있는 구조와 “FE 입력 vs OCR 나란히 비교” 기능을 함께 사용할 수 있음.

---

## 5. BE 구현 포인트 (FE 입력값 저장·노출)

| 위치 | 작업 |
|------|------|
| **DB** | `submissions` 테이블에 `user_input_snapshot JSONB NULL` 컬럼 추가 (마이그레이션). |
| **모델** | `Submission` 클래스에 `user_input_snapshot = Column(JSONB, nullable=True)` 추가. |
| **Complete 처리** | `_submit_receipt_common` 내부에서 `req.data`가 있으면 `submission.user_input_snapshot = req.data.model_dump()` (또는 동등한 JSON) 저장 후 commit. (현재 complete-legacy만 req.data를 받으므로, complete-legacy 경로 또는 공통 함수에서 저장.) |
| **Admin 상세** | `admin_get_submission` 응답의 `submission` 딕셔너리에 `user_input_snapshot` 키 추가 (DB 값 그대로 또는 null). |
