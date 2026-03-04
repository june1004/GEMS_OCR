# 테스트용 FE 적용 가이드

> 테스트 프론트엔드에서 영수증 OCR API를 **순서대로** 연동할 때 참고하는 가이드.  
> 규격은 **FE_API_규격_문서_외부전달용.md** 를 기준으로 합니다.

---

## 0. 사전 준비

### 0.1 API Base URL

- 테스트 서버 Base URL을 환경 변수 또는 설정에 넣습니다.  
  예: `VITE_API_BASE=https://api.nanum.online` (Vite) 또는 `REACT_APP_API_BASE=...` (CRA).
- 연동 시 **프록시**를 쓰면 `/api` 만 두고, Presigned 응답의 `uploadUrl`은 그대로 사용합니다.

### 0.2 사용자 식별자

- 테스트용 `userUuid` 하나를 고정해 두고, Presigned·Complete·Status에서 동일하게 사용합니다.

---

## 1. 연동 순서 (4단계)

| 단계 | API | FE 동작 |
|------|-----|---------|
| 1 | Presigned URL 발급 | 업로드할 이미지 정보로 URL·receiptId·objectKey 받기 |
| 2 | 이미지 업로드 | 받은 URL로 이미지 PUT (추가 장은 같은 receiptId로 1번 다시 호출 후 업로드) |
| 3 | Complete | receiptId, userUuid, type, documents, (선택) data 전송 |
| 4 | Status 조회 | 같은 receiptId로 결과 폴링 또는 콜백 수신 |

---

## 2. 1단계 — Presigned URL 발급

**요청**

- Method: `POST`
- URL: `${baseUrl}/api/v1/receipts/presigned-url`
- Body: Query 또는 Form  
  - `fileName`: 파일명 (예: `receipt.jpg`)  
  - `contentType`: `image/jpeg` 또는 `image/png`  
  - `userUuid`: 테스트용 사용자 ID  
  - `type`: `STAY` 또는 `TOUR`  
  - `receiptId`: (선택) 같은 신청에 2장째 이상 올릴 때만, 1장째에서 받은 receiptId 전달

**응답에서 꼭 저장할 값**

- `receiptId` → 신청 ID (Complete·Status에서 사용)
- `objectKey` → Complete 요청의 `documents[].imageKey`에 그대로 사용
- `uploadUrl` → 2단계 PUT 요청 URL

**예시 (fetch)**

```javascript
const params = new URLSearchParams({
  fileName: file.name,
  contentType: file.type || 'image/jpeg',
  userUuid: 'test-user-001',
  type: 'TOUR',
});
const res = await fetch(`${baseUrl}/api/v1/receipts/presigned-url?${params}`, {
  method: 'POST',
});
const { uploadUrl, receiptId, objectKey } = await res.json();
// receiptId, objectKey 저장 후 2단계에서 uploadUrl로 PUT
```

---

## 3. 2단계 — 이미지 업로드

**요청**

- Method: `PUT`
- URL: 1단계 응답의 `uploadUrl`
- Body: 이미지 파일 바이너리 (Blob/File 그대로 전송)

**예시 (fetch)**

```javascript
await fetch(uploadUrl, {
  method: 'PUT',
  body: file,  // File 또는 Blob
  headers: { 'Content-Type': file.type || 'image/jpeg' },
});
// 성공 후 objectKey를 documents[].imageKey로 사용
```

- **영수증 2장 이상**: 1장 업로드 후, **같은 receiptId**로 Presigned를 다시 호출해 2장째 uploadUrl을 받고, 그 URL로 두 번째 이미지 PUT. 받은 `objectKey`들을 모아서 3단계 `documents` 배열에 넣습니다.

---

## 4. 3단계 — Complete (검증 요청)

**요청**

- Method: `POST`
- URL: `${baseUrl}/api/v1/receipts/complete`
- Content-Type: `application/json`
- Body: 아래 JSON (테스트 시 `data` 는 생략 가능)

**최소 Body (documents만 — 검수 없는 방식)**

```json
{
  "receiptId": "1단계에서 받은 receiptId",
  "userUuid": "test-user-001",
  "type": "TOUR",
  "documents": [
    { "imageKey": "1장째 objectKey", "docType": "RECEIPT" }
  ]
}
```

**테스트용 Body (여러 폼데이터 — data.items[] 사용)**

- 영수증 2장일 때 예시 (TOUR):

```json
{
  "receiptId": "1단계에서 받은 receiptId",
  "userUuid": "test-user-001",
  "type": "TOUR",
  "documents": [
    { "imageKey": "receipts/xxx_a.jpg", "docType": "RECEIPT" },
    { "imageKey": "receipts/xxx_b.jpg", "docType": "RECEIPT" }
  ],
  "data": {
    "items": [
      { "amount": 50000, "payDate": "2026-02-15", "storeName": "A식당" },
      { "amount": 70000, "payDate": "2026-02-15", "storeName": "B카페" }
    ]
  }
}
```

- **규칙**: `documents`와 `data.items` **길이·순서 동일**. `documents[i]` 와 `data.items[i]` 가 같은 장.

**예시 (fetch)**

```javascript
const body = {
  receiptId,
  userUuid: 'test-user-001',
  type: 'TOUR',
  documents: collectedDocs,  // [{ imageKey, docType }, ...]
  // data: { items: [...] }  // 선택
};
const res = await fetch(`${baseUrl}/api/v1/receipts/complete`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});
const { status, receiptId: id } = await res.json();
// status === 'PROCESSING' 이면 4단계로
```

**응답**

- `{ "status": "PROCESSING", "receiptId": "..." }` → 4단계에서 같은 receiptId로 결과 조회.

---

## 5. 4단계 — 결과 조회 (Status)

**요청**

- Method: `GET`
- URL: `${baseUrl}/api/v1/receipts/{receiptId}/status`

**폴링**

- Complete 직후 한 번 호출 후, `shouldPoll === true` 이면 `recommendedPollIntervalMs`(예: 2000) 후 다시 호출.
- `statusStage === "DONE"` 이거나 `shouldPoll === false` 이면 폴링 중지.

**예시 (fetch)**

```javascript
const res = await fetch(`${baseUrl}/api/v1/receipts/${receiptId}/status`);
const data = await res.json();
// data.overall_status, data.total_amount, data.items, data.shouldPoll, data.recommendedPollIntervalMs
```

**응답에서 테스트 시 확인할 값**

- `overall_status`: FIT / UNFIT_* / PENDING_* 등
- `items[]`: 장별 `status`, `error_code`, `error_message`, `extracted_data`(OCR 결과)

---

## 6. 테스트 시나리오 요약

| 시나리오 | 1단계 | 2단계 | 3단계 Body | 비고 |
|----------|--------|--------|------------|------|
| **단일 장 (documents만)** | Presigned 1회, type=TOUR | PUT 1회 | documents 1개, data 없음 | 가장 단순 |
| **2장 (documents만)** | Presigned 2회 (2번째에 receiptId 전달) | PUT 2회 | documents 2개, data 없음 | OCR만 판정 |
| **2장 + 폼데이터** | 위와 동일 | PUT 2회 | documents 2개 + data.items 2개 | 장별 금액·날짜 전달, 검수 흐름 테스트 |

---

## 7. 에러 처리

- 4xx/5xx: 응답 JSON의 `detail` 메시지 표시.
- 409: receiptId type 불일치 또는 이미 완료된 신청 → receiptId 새로 발급 후 다시 시도.

---

## 8. 체크리스트 (테스트 FE)

- [ ] Base URL 설정 후 Presigned 호출 성공
- [ ] uploadUrl로 PUT 업로드 성공, objectKey 수집
- [ ] Complete 호출 시 receiptId·userUuid·type·documents 전달
- [ ] (선택) 2장 이상 시 data.items[] 로 동일 순서·길이 전달
- [ ] Status 폴링으로 최종 overall_status·items 확인
- [ ] 에러 시 detail 메시지 표시

이 순서대로 적용하면 테스트용 FE에서 API 연동을 끝까지 검증할 수 있습니다.
