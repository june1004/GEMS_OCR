# GEMS OCR FE 연동 API Spec (1-Page)

## 목적
- FE에서 영수증/증빙 이미지를 업로드하고, `STAY` / `TOUR` 규칙에 맞게 검증 요청 및 결과 조회를 수행한다.
- 기본 원칙: **파일은 개별 업로드(PUT), 결과는 대표 `receiptId`로 묶어 제출(POST /complete)**.

---

## 1) Presigned URL 발급
### Endpoint
- `POST /api/v1/receipts/presigned-url`

### Query Params
- `fileName` (required)
- `contentType` (required, 예: `image/jpeg`)
- `userUuid` (required)
- `type` (required): `STAY` | `TOUR`
- `receiptId` (optional): 기존 신청에 이미지 추가 업로드 시 사용

### 요청 예시 (첫 호출: 신규 receiptId 발급)
`POST /api/v1/receipts/presigned-url?fileName=tour_01.jpg&contentType=image%2Fjpeg&userUuid=user-123&type=TOUR`

### 요청 예시 (추가 이미지: 기존 receiptId 재사용)
`POST /api/v1/receipts/presigned-url?fileName=tour_02.jpg&contentType=image%2Fjpeg&userUuid=user-123&type=TOUR&receiptId=6f1849a9-...`

### 응답
```json
{
  "uploadUrl": "https://...presigned...",
  "receiptId": "6f1849a9-4f26-4c4f-a2de-5a8e3f1a8f2d",
  "objectKey": "receipts/6f1849a9-..._ab12cd34_tour_01.jpg"
}
```

---

## 2) 파일 업로드
### Endpoint
- `PUT {uploadUrl}`

### Header/Body
- `Content-Type: image/jpeg` (또는 png)
- Body: binary file

---

## 3) 검증 요청 (Complete)
### Endpoint
- `POST /api/v1/receipts/complete`

### 권장 요청 모델 (`documents`)
- `type`은 `STAY` / `TOUR`만 허용
- `documents[].docType`:
  - `RECEIPT` (일반 영수증)
  - `OTA_INVOICE` (숙박 OTA 명세서)

### STAY 예시
```json
{
  "receiptId": "6f1849a9-4f26-4c4f-a2de-5a8e3f1a8f2d",
  "userUuid": "user-123",
  "campaignId": 1,
  "type": "STAY",
  "documents": [
    { "imageKey": "receipts/..._stay_receipt.jpg", "docType": "RECEIPT" },
    { "imageKey": "receipts/..._stay_invoice.jpg", "docType": "OTA_INVOICE" }
  ]
}
```

### TOUR 예시 (1~3장)
```json
{
  "receiptId": "b4fa5ac2-0fca-4df4-a6f7-fcc7d472ef9a",
  "userUuid": "user-123",
  "campaignId": 1,
  "type": "TOUR",
  "documents": [
    { "imageKey": "receipts/..._tour_01.jpg", "docType": "RECEIPT" },
    { "imageKey": "receipts/..._tour_02.jpg", "docType": "RECEIPT" },
    { "imageKey": "receipts/..._tour_03.jpg", "docType": "RECEIPT" }
  ]
}
```

### 응답
```json
{
  "status": "PROCESSING",
  "receiptId": "6f1849a9-4f26-4c4f-a2de-5a8e3f1a8f2d"
}
```

> 하위호환: 기존 `data` 방식도 허용되지만, 신규 연동은 `documents` 사용 권장.

---

## 4) 상태 조회 (Polling)
### Endpoint
- `GET /api/v1/receipts/{receiptId}/status`
- 별칭: `GET /api/v1/receipts/status/{receiptId}`

### 응답 예시
```json
{
  "status": "FIT",
  "amount": 70000,
  "failReason": null,
  "rewardAmount": 30000,
  "address": "강원특별자치도 춘천시 ...",
  "cardPrefix": "1234"
}
```

---

## 5) FE 구현 체크리스트
- `type` 값은 반드시 `STAY` / `TOUR` 사용 (`SPEND` 미지원)
- 첫 presigned 응답의 `receiptId`를 저장하고, 추가 이미지는 같은 `receiptId`로 발급 요청
- 업로드 성공 후 `objectKey`를 `documents[].imageKey`로 사용
- STAY: `RECEIPT` 1장 필수, `OTA_INVOICE`는 필요 시 추가
- TOUR: `RECEIPT` 1~3장
- `/complete` 이후 status polling으로 최종 판정 확인
