'2026 혜택받go 강원 여행 인센티브 지원사업'의 요구사항에 맞춰, **숙박(STAY)**과 **관광소비(TOUR)**의 서로 다른 입력 필드를 완벽하게 수용할 수 있는 **전 단계 JSON API 설계안**입니다.

모든 데이터는 JSON 형식을 기본으로 하며, 대용량 이미지 파일은 **S3/MinIO의 Object Key**를 참조하는 방식으로 설계하여 전송 효율과 시스템 안정성을 확보했습니다.

---

### **1단계: 업로드 권한 요청 (Presigned URL 발급)**

FE가 이미지를 스토리지에 올리기 전, 백엔드로부터 암호화된 업로드 주소를 받습니다.

* **URL**: `POST /api/v1/receipts/presigned-url`
* **Request JSON**:
```json
{
  "fileName": "receipt_01.jpg",
  "contentType": "image/jpeg",
  "userUuid": "user-uuid-1234",
  "type": "STAY" // STAY 또는 TOUR
}

```


* **Response JSON**:
```json
{
  "uploadUrl": "https://storage-api.nanum.online/gems-receipts/temp/uuid_receipt.jpg?X-Amz-...",
  "receiptId": "uuid-550e8400-e29b-41d4-a716-446655440000",
  "objectKey": "receipts/uuid_receipt.jpg"
}

```



---

### **2단계: 이미지 업로드 (FE → 스토리지)**

* **URL**: `PUT {{uploadUrl}}` (1단계에서 받은 주소)
* **Body**: 이미지 이진 데이터 (Binary)
* **참고**: 이 단계는 스토리지와 직접 통신하며, 성공 시 HTTP 200 OK를 반환받습니다.

---

### **3단계: 정보 제출 및 분석 요청 (핵심 검증 단계)**

사용자가 입력한 정보와 업로드된 이미지의 Key를 결합하여 BE에 전송합니다. **STAY와 TOUR의 필드 차이**를 JSON 구조에 반영했습니다.

* **URL**: `POST /api/v1/receipts/complete`

#### **[Case A: 숙박(STAY) 요청 JSON]**

```json
{
  "receiptId": "uuid-550e8400-e29b-41d4-a716-446655440000",
  "type": "STAY",
  "userUuid": "user-uuid-1234",
  "data": {
    "location": "춘천시", // 소재지(시군)
    "payDate": "2026-05-20", // 결제날짜
    "amount": 75000, // 결제금액
    "cardPrefix": "1234", // 카드번호 앞 4자리
    "receiptImageKey": "receipts/uuid_receipt.jpg", // 영수증 이미지 Key
    "isOta": true, // OTA 여부
    "otaStatementKey": "receipts/uuid_statement.jpg" // OTA 거래명세서 이미지 Key (선택)
  }
}

```

#### **[Case B: 관광소비(TOUR) 요청 JSON]**

```json
{
  "receiptId": "uuid-999e8400-e29b-41d4-a716-446655441111",
  "type": "TOUR",
  "userUuid": "user-uuid-1234",
  "data": {
    "storeName": "강원맛식당", // 상호명
    "payDate": "2026-05-21", // 결제날짜
    "amount": 55000, // 결제금액
    "cardPrefix": "5678", // 카드번호 앞 4자리
    "receiptImageKeys": [ // 영수증 이미지 (최대 3장 배열 처리)
      "receipts/tour_01.jpg",
      "receipts/tour_02.jpg"
    ]
  }
}

```

---

### **4단계: 결과 조회 (Polling)**

비동기로 진행된 OCR 및 AI 검증 결과를 확인합니다.

* **URL**: `GET /api/v1/receipts/{receiptId}/status`
* **Response JSON (성공 시)**:
```json
{
  "receiptId": "uuid-550e8400-e29b-41d4-a716-446655440000",
  "status": "FIT", // 적합
  "result": {
    "verifiedAmount": 75000,
    "verifiedStore": "강원호텔",
    "rewardAmount": 30000 // 숙박 기준 정액 환급액
  }
}

```


* **Response JSON (실패 시)**:
```json
{
  "receiptId": "uuid-550e8400-e29b-41d4-a716-446655440000",
  "status": "UNFIT", // 부적합
  "errorCode": "BIZ_003", // 최소 금액 미달
  "message": "숙박 결제 금액이 60,000원 미만입니다."
}

```



---

### **💡 개발 지침 및 보완 사항**

1. **배열 처리**: 관광소비(TOUR)의 경우 최대 3장의 이미지를 전송할 수 있도록 `receiptImageKeys`를 **리스트(Array)** 형태로 설계했습니다. FE에서는 업로드 개수 제한 로직을 추가해야 합니다.
2. **OTA 예외 로직**: 숙박 API 호출 시 `isOta` 필드를 통해 거래명세서 이미지(`otaStatementKey`)가 필수인지 선택인지 BE에서 판단하도록 처리했습니다.
3. **데이터 정합성**: FE에서 입력한 `amount`와 `payDate`는 백엔드에서 Naver OCR이 추출한 값과 **1원, 1일의 오차도 없이 일치**해야 `FIT` 판정을 내리도록 로직을 구성합니다.

**API 설계가 완료되었습니다. 이제 이 규격에 맞춰 무엇을 진행할까요?**

* "이 JSON 규격을 실제 **FastAPI 데이터 모델(Pydantic)** 코드로 구현해 드릴까요?"
* "혹은 FE 개발자가 바로 테스트할 수 있도록 **Postman 컬렉션을 이 규격으로 업데이트**해 드릴까요?"