# FE ↔ FastAPI 개발자 가이드 (영수증 업로드/검증/결과 수신)

> 대상: FE 개발자  
> 목적: “신청(Submission)” 단위로 영수증(1~N장)을 업로드하고, OCR/판정 결과를 **콜백 또는 status 조회**로 받는 전체 구현 가이드.

---

## 0) 핵심 개념: **신청(Submission) = receiptId 1개**

- **receiptId = submission_id = 신청(Submission) 1건의 대표 ID**
- “이미지 1장”이 아니라 **신청 1건**을 기준으로 판정(FIT/UNFIT/PENDING_*)이 내려갑니다.
- 이미지가 여러 장이면 **반드시 같은 receiptId로 묶어서** 제출해야 “합산/조합 판정”이 됩니다.

### 유형별 허용 이미지 수/조합

| type | 의미 | documents 허용 |
|------|------|----------------|
| **STAY** | 숙박 | `RECEIPT` 1장 필수 + `OTA_INVOICE` 0~1장 |
| **TOUR** | 관광 소비 | `RECEIPT` 1~3장 |

---

## 1) End-to-End 플로우

### Step 1. Presigned URL 발급 (업로드 권한)

**API**: `POST /api/v1/receipts/presigned-url`  
(프록시 별칭: `POST /api/proxy/presigned-url`)

**요청 파라미터(Query/Form)**:
- `fileName` (필수)
- `contentType` (필수, 예: `image/jpeg`)
- `userUuid` (필수)
- `type` (필수, `STAY` | `TOUR`)
- `receiptId` (선택) — **같은 신청에 추가 이미지 업로드**할 때만 기존 receiptId 전달

**응답**

```json
{
  "uploadUrl": "https://...presigned...",
  "receiptId": "uuid",
  "objectKey": "receipts/uuid_xxx.jpg"
}
```

**중요**image.png
- 첫 이미지에서 받은 `receiptId`를 **신청 ID로 저장**하세요.
- 추가 이미지 업로드 시엔 `receiptId`를 재사용해야 “1건 신청”으로 묶입니다.
- `receiptId` 재사용은 **같은 type(STAY↔STAY, TOUR↔TOUR)** 에서만 허용됩니다. 다른 type으로 재사용 시 **409(type mismatch)** 로 차단됩니다.

---

### Step 2. 이미지 업로드 (FE → MinIO/S3)

**업로드 방식 A (권장): Presigned PUT**
- Step 1의 `uploadUrl`로 이미지 파일을 **PUT 업로드**
- 업로드 성공 시, Step 1 응답의 `objectKey`를 보관 (Step 3에 `documents[].imageKey`로 전달)

**업로드 방식 B (대안): FormData 업로드**

스토리지 CORS 등의 사유로 Presigned 업로드가 어려우면 아래 API 사용:

**API**: `POST /api/v1/receipts/upload` (multipart/form-data)

Form fields:
- `file` (필수, binary)
- `userUuid` (필수)
- `type` (필수, `STAY` | `TOUR`)

응답:

```json
{
  "uploadUrl": "",
  "receiptId": "uuid",
  "objectKey": "receipts/uuid_filename.jpg"
}
```

**중요**
- 이 경로는 **항상 새 receiptId를 생성**합니다. (추가 업로드로 “묶기”를 지원하지 않음)
- “1건 신청에 여러 장”을 반드시 지원해야 한다면 Presigned 방식을 권장합니다.

---

### Step 3. Complete (검증/분석 요청)

**API**: `POST /api/v1/receipts/complete` (documents-only)

**Body(JSON)**:
- `receiptId` (필수) — Step1에서 받은 값
- `userUuid` (필수) — presigned 발급 시 사용한 값과 동일
- `type` (필수) — `STAY` | `TOUR`
- `documents` (권장): 업로드한 이미지 목록
  - 각 원소 `{ "imageKey": "<objectKey>", "docType": "RECEIPT" | "OTA_INVOICE" }`
- `data` (레거시): documents 대신 사용할 수 있으나 필수 필드가 많아 운영에선 documents 방식 권장
  - STAY의 `location`은 FE 입력이 없어도 되며(null 허용), 운영/자산화 목적의 location은 OCR 인식 결과를 기준으로 저장됩니다.
  - FE 신규 구현은 `data`를 사용하지 않는 것을 권장합니다. (혼동 방지를 위해 v1 연동은 documents-only로 운영)
- **data(폼 데이터)를 보낼 때**: BE는 **OCR 데이터를 우선**하여 비교·판정합니다. OCR 신뢰도가 높으면 OCR 값만 사용하고, 낮을 때만 FE 입력(금액·결제일·지역 등)을 참조값으로 사용합니다. FE 입력 금액과 OCR 금액이 10% 이상 차이나면 `PENDING_VERIFICATION`(수동 검증 대기)으로 두어, 관리자가 상세 조회 후 **override** API로 FIT/UNFIT 등 최종 판정(검수 완료)을 내리도록 되어 있습니다.

예시(STAY):

```json
{
  "receiptId": "uuid",
  "userUuid": "user-123",
  "type": "STAY",
  "documents": [
    { "imageKey": "receipts/uuid_a.jpg", "docType": "RECEIPT" },
    { "imageKey": "receipts/uuid_b.jpg", "docType": "OTA_INVOICE" }
  ]
}
```

예시(TOUR):

```json
{
  "receiptId": "uuid",
  "userUuid": "user-123",
  "type": "TOUR",
  "documents": [
    { "imageKey": "receipts/uuid_a.jpg", "docType": "RECEIPT" },
    { "imageKey": "receipts/uuid_b.jpg", "docType": "RECEIPT" }
  ]
}
```

**응답**

```json
{
  "status": "PROCESSING",
  "receiptId": "uuid"
}
```

**중요**
- Complete는 **receiptId당 1회 호출**이 원칙입니다. (documents에 해당 신청의 모든 이미지 포함)
- 이미 처리 중이면 `PROCESSING` 또는 `VERIFYING`으로 동일 receiptId 반환될 수 있습니다.
- `receiptId` 생성 시점의 type과 다른 type으로 complete 호출 시 **409(type mismatch)** 로 차단됩니다.

---

## 2) 결과 수신 방법 (콜백 + 복구용 status 조회)

### A. 콜백(운영 기본)

BE는 분석 완료 시점에 환경변수 `OCR_RESULT_CALLBACK_URL`로 결과를 **POST 1회** 전송합니다.

- 운영: `https://easy.gwd.go.kr/dg/coupon/api/ocr/result`
- 테스트: `http://210.179.205.50/dg/coupon/api/ocr/result`

#### 콜백 payload 특징
- `GET /api/v1/receipts/{receiptId}/status`와 거의 동일한 구조
- 전송 최적화:
  - `items[].ocr_raw`는 **콜백에 포함되지 않음**
  - `audit_trail`, `items[].error_message`는 길이 제한(truncate)될 수 있음
- 공통 필드:
  - `schemaVersion` (현재 2)
  - `receiptId` (필수)
  - `payloadMeta` (truncate 여부/생성시각)

### B. GET status (폴링/스케줄러 복구)

콜백 누락/장애 대비용으로, FE 시스템은 스케줄러로 아래 API를 호출해 최종 상태를 동기화할 수 있습니다.

**API**: `GET /api/v1/receipts/{receiptId}/status`  
(별칭: `/api/v1/receipts/status/{receiptId}`, `/api/proxy/status/{receiptId}`)

응답에는 폴링 힌트가 포함됩니다:
- `shouldPoll` (true/false)
- `recommendedPollIntervalMs` (권장 폴링 간격)
- `reviewRequired` (수동 검토 필요 여부)
- `statusStage` (`AUTO_PROCESSING | MANUAL_REVIEW | DONE`)

---

## 3) “장별” 에러코드 처리 (items[].error_code)

신청 단위 판정과 별개로, 각 이미지(item)별로 사유가 내려옵니다.

- `items[].status`: FIT / PENDING_NEW / PENDING_VERIFICATION / UNFIT_* / ERROR_OCR 등
- `items[].error_code`: BIZ_*, OCR_*, PENDING_* 등
- `items[].error_message`: 한글 메시지(트러블슈팅/표시용)

FE는 결과 화면에서 **이미지별로 error_code/error_message**를 표시하면 운영/CS 대응이 쉬워집니다.

---

## 4) 데이터 정규화(표시/자산화)

BE는 저장 시점에 아래를 정규화합니다.
- 결제일 `pay_date`: `YYYY/MM/DD`
- 사업자번호 `biz_num`: `000-00-00000` (가능할 때)
- 전화번호 `tel`: 하이픈 포맷
- 주소 `address`: 공백 정리, `강원도` → `강원특별자치도`

따라서 FE는 표시에 별도 정규화를 하지 않아도 “일관된 포맷”을 받을 수 있습니다.

---

## 5) FE 구현 체크리스트(중요)

- **receiptId 유지**
  - [ ] 첫 presigned 응답의 receiptId를 “신청 ID”로 저장했는가?
  - [ ] 추가 이미지 업로드 시 같은 receiptId로 presigned를 다시 받았는가?
- **documents 구성**
  - [ ] documents[].imageKey는 presigned 응답의 objectKey인가?
  - [ ] STAY: RECEIPT 1장 + OTA_INVOICE 0~1장 규칙을 지켰는가?
  - [ ] TOUR: RECEIPT만 1~3장 규칙을 지켰는가?
- **complete 호출**
  - [ ] receiptId당 complete를 1회만 호출했는가?
  - [ ] userUuid owner mismatch가 나지 않도록 동일 userUuid로 호출했는가?
- **결과 수신**
  - [ ] 콜백 수신 후 receiptId로 DB 유효성 검증을 하는가?
  - [ ] 콜백 누락 대비 스케줄러로 GET status를 호출해 복구하는가?
- **에러 표시**
  - [ ] items[].error_code/error_message를 이미지별로 표시할 수 있는가?

---

## 참고 문서

- 상세 스펙/에러코드: `FE_FASTAPI_API_SPEC.md`
- 외부 공유용 요약: `FE_API_SPEC_EXTERNAL.md`
- 1페이지 요약: `FE_API_SPEC_ONE_PAGE.md`

