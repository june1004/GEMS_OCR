# FE ↔ FastAPI API 연동 명세 (초안)

> 프론트엔드(FE)와 GEMS OCR FastAPI 백엔드(BE) 간 호출 규약 및 **영수증 장별 에러코드** 포함.

---

## 1. 공통 사항

| 항목 | 내용 |
|------|------|
| **Base URL** | 배포 환경에 따라 설정 (예: `https://api.example.com` 또는 `/api` 프록시) |
| **Content-Type** | `application/json` (POST body 있는 API) |
| **에러 응답** | 4xx/5xx 시 JSON `{"detail": "메시지"}` |
| **유형** | `STAY`(숙박), `TOUR`(관광) 만 사용 |

---

## 2. 전체 흐름 (4단계)

| 단계 | FE 동작 | BE API | 비고 |
|------|--------|--------|------|
| 1 | 업로드 URL 발급 | `POST /api/v1/receipts/presigned-url` | receiptId·uploadUrl·objectKey 수신 |
| 2 | Presigned URL로 이미지 업로드 | (S3/MinIO 직접 **PUT**) | FE → 스토리지, objectKey는 3단계에서 imageKey로 전달 |
| 3 | 검증 요청(이미지 목록 전달) | `POST /api/v1/receipts/complete` | receiptId 동일하게 전달 |
| 4 | 결과 조회(폴링) | `GET /api/v1/receipts/{receiptId}/status` | shouldPoll·recommendedPollIntervalMs 참고 |

---

## 3. API 상세

### 3.1 Presigned URL 발급

- **Method**: `POST`
- **URL**: `/api/v1/receipts/presigned-url`
- **요청**: Query 또는 Form (`application/x-www-form-urlencoded`)
  - `fileName`: string (파일명)
  - `contentType`: string (예: `image/jpeg`)
  - `userUuid`: string (사용자 식별자)
  - `type`: `"STAY"` \| `"TOUR"`
  - `receiptId`: string (선택) — 같은 신청으로 추가 업로드 시 기존 receiptId

**Response (200)**

```json
{
  "uploadUrl": "https://...",
  "receiptId": "uuid",
  "objectKey": "receipts/uuid_xxx.jpg"
}
```

- FE는 `uploadUrl`로 **PUT** 요청해 파일 업로드.  
- `objectKey`는 3단계 Complete 요청의 `documents[].imageKey`로 그대로 전달.
- `receiptId`를 재사용할 때는 **동일 type(STAY↔STAY, TOUR↔TOUR)** 인 경우에만 허용되며, 다른 type으로 재사용하면 **409(type mismatch)** 로 차단됩니다.

---

### 3.2 검증 완료 요청 (Complete)

- **Method**: `POST`
- **URL**: `/api/v1/receipts/complete`
- **Body (JSON)**:
  - `receiptId`: string (1단계에서 받은 것)
  - `userUuid`: string
  - `type`: `"STAY"` \| `"TOUR"`
  - `documents`: 배열 — 각 항목 `{ "imageKey": "objectKey", "docType": "RECEIPT" | "OTA_INVOICE" }`
    - STAY: RECEIPT 1장 필수, OTA 명세서 있으면 `docType: "OTA_INVOICE"` 1건 추가
    - TOUR: RECEIPT만 1~3장

> 참고: 내부 호환을 위해 legacy `data`(수기 보정값) 경로가 존재할 수 있으나, FE 신규 구현은 **documents만 전송**하면 됩니다.  
> 자산화/관리 목적 필드(location 등)는 **OCR 인식 결과를 기준으로 저장**되며, FE가 입력을 책임질 필요가 없습니다.

- type은 receiptId 생성 시점에 고정되며, 다른 type으로 complete 호출 시 **409(type mismatch)** 로 차단됩니다.
> 참고: campaignId는 내부 운영/자산화용이며, v1 연동( documents-only )에서는 FE가 전달하지 않습니다.

**Response (200)**

```json
{
  "status": "PROCESSING",
  "receiptId": "uuid"
}
```

- 이미 처리 중이면 `status`가 `"PROCESSING"` 또는 `"VERIFYING"`으로 동일 receiptId 반환.
- 이후 FE는 **같은 receiptId**로 4단계 status를 폴링.

---

### 3.3 결과 조회 (Status) — 폴링용

- **Method**: `GET`
- **URL**: `/api/v1/receipts/{receiptId}/status`  
  - 별칭: `/api/v1/receipts/status/{receiptId}`, `/api/proxy/status/{receiptId}`

**Response (200) — 공통 필드**

| 필드 | 타입 | 설명 |
|------|------|------|
| submission_id | string (UUID) | 신청 번호 |
| project_type | "STAY" \| "TOUR" | 유형 |
| overall_status | string | 신청 단위 최종 상태 |
| status | string | (하위호환) overall_status와 동일 |
| total_amount | int | FIT 항목 합산 금액 |
| amount | int | (하위호환) total_amount와 동일 |
| global_fail_reason | string \| null | 사업 기준 미달 사유 |
| failReason | string \| null | (하위호환) 동일 |
| audit_trail | string | 판정 근거 요약 |
| rewardAmount | int | 10000(TOUR FIT) / 30000(STAY FIT) / 0 |
| address | string \| null | 가맹점 주소(첫 장 기준) |
| cardPrefix | string \| null | 카드 앞 4자리. **0000**=현금, **1000**=카드번호 없음/****, 그 외=실제 마지막 4자리 |
| shouldPoll | boolean | true면 같은 URL로 재호출 권장 |
| recommendedPollIntervalMs | int \| null | 권장 폴링 간격(ms) |
| reviewRequired | boolean | 관리자 검토 대기 여부 |
| statusStage | string | "AUTO_PROCESSING" \| "MANUAL_REVIEW" \| "DONE" |
| items | array | **영수증 장별 목록** (아래 참조) |

**items[] — 영수증 장별**

| 필드 | 타입 | 설명 |
|------|------|------|
| item_id | string (UUID) | 장별 ID |
| status | string | 해당 장 판정 (FIT / PENDING / UNFIT_* / ERROR_OCR 등) |
| **error_code** | string \| null | **장별 에러코드** (부적합/오류 시) |
| **error_message** | string \| null | **에러 메시지(한글)** |
| extracted_data | object \| null | store_name, amount, pay_date, address, card_num(0000=현금, 1000=카드없음, 4자리=실제) |
| image_url | string | MinIO object key |
| ocr_raw | object \| null | 원본 OCR JSON (있을 경우) |

---

### 3.4 (선택) 활성 캠페인 조회

캠페인이 1개(기본)인 경우 FE는 이 API를 호출할 필요가 없습니다.  
향후 캠페인 다중 운영(기간/지역 이벤트 등) 확장 시, FE가 화면에 표시하거나 운영/디버깅 목적으로 사용할 수 있습니다.

- **Method**: `GET`
- **URL**: `/api/v1/campaigns/active`

**Response (200)**

```json
{
  "defaultCampaignId": 1,
  "items": [
    {
      "campaignId": 1,
      "name": "2026 혜택받go 강원 여행 인센티브",
      "active": true,
      "targetCityCounty": null,
      "startDate": null,
      "endDate": null,
      "projectType": null,
      "priority": 100
    }
  ]
}
```

## 4. 영수증 장별 에러코드 (items[].error_code)

각 영수증 이미지(`items[]`)에 대해 `error_code`·`error_message`가 채워질 수 있습니다.  
신청 단위(`overall_status` / `failReason`)와 함께 FE에서 **장별로 어떤 사유로 부적합/대기인지** 표시할 때 사용합니다.

### 4.1 에러코드 목록 (코드 → 의미)

| error_code | error_message (예시) | 설명 |
|------------|----------------------|------|
| **BIZ_001** | BIZ_001 (중복 등록) | 동일 영수증(사업자번호·결제일·금액·카드) 중복 제출 |
| **BIZ_002** | BIZ_002 (2026년 결제일 아님) | 결제일이 2026년이 아님 |
| **BIZ_003** | BIZ_003 (최소 금액 미달) | TOUR 5만원/STAY 6만원 미달 |
| **BIZ_004** | BIZ_004 (강원특별자치도 외 지역) | 상점 소재지가 강원도 외 |
| **BIZ_005** | BIZ_005 (캠페인 기간 아님) | 캠페인 기간 외 |
| **BIZ_006** | BIZ_006 (캠페인 대상 지역 아님) | 캠페인 대상 시군 아님 |
| **BIZ_007** | BIZ_007 (입력 금액과 OCR 금액 불일치) | 사용자 입력 금액과 OCR 금액 불일치 |
| **BIZ_008** | BIZ_008 (유흥업소 등 부적격 업종) | 유흥·단란주점 등 제외 업종 |
| **BIZ_010** | BIZ_010 (문서 구성 요건 불충족) | STAY/TOUR 문서 개수·종류 요건 미충족 |
| **BIZ_011** | BIZ_011 (영수증/증빙 금액 불일치) | 숙박 영수증 금액과 OTA 명세서 금액 불일치 |
| **OCR_001** | OCR_001 (영수증 판독 불가) | OCR 실패·판독 불가 |
| **OCR_002** | OCR_002 (결제일 형식 오류) | 결제일 파싱 실패 |
| **OCR_003** | OCR_003 (마스터 상호 미등록) | 마스터에 없는 상점(내부용, FE에는 PENDING_NEW 등으로 노출) |
| **OCR_004** | OCR_004 (인식 불량·수동 검수 보정) | 상점명·사업자·주소 등 누락 또는 저신뢰도 → 관리자 검수 후 보정 |
| **PENDING_NEW** | PENDING_NEW (신규 상점 검수 대기) | 신규 상점으로 관리자 검토 대기 |
| **PENDING_VERIFICATION** | PENDING_VERIFICATION (사용자 입력값- OCR 불일치) | 금액 등 사용자 입력과 OCR 불일치로 수동 검증 대기 |
| **UNFIT_CATEGORY** | UNFIT_CATEGORY (제외 업종) | 제외 업종(BIZ_008 등과 동일 의미로 정규화) |
| **UNFIT_REGION** | UNFIT_REGION (지역 불일치) | 지역 요건 불충족 |
| **UNFIT_DATE** | UNFIT_DATE (기간/날짜 불일치) | 결제일/기간 요건 불충족 |
| **UNFIT_DUPLICATE** | UNFIT_DUPLICATE (중복 제출) | 중복 제출(BIZ_001과 동일 의미로 정규화) |
| **ERROR_OCR** | ERROR_OCR (판독 불가) | 해당 장 OCR 실패 |

- BE는 내부적으로 위 코드를 **정규화**해 `items[].error_code`로 내려주며, `error_message`는 위 표와 같은 한글 메시지로 매핑됩니다.
- FE는 `items[].error_code` + `items[].error_message`로 **장별** 안내 문구를 구성하면 됩니다.

### 4.2 신청 단위 상태 (overall_status)와의 관계

- `overall_status`가 `FIT`이면 리워드 지급 대상.
- `UNFIT_*`, `ERROR_OCR`, `PENDING_NEW`, `PENDING_VERIFICATION` 등은 `failReason` / `global_fail_reason`과 `audit_trail`로 사유 확인.
- 장별로는 `items[].status`와 `items[].error_code`로 **어느 장이 어떤 사유인지** 구분 가능.

---

## 5. 폴링 가이드

- **shouldPoll === true**  
  - `recommendedPollIntervalMs`(예: 2000 또는 30000) 후 같은 `GET /api/v1/receipts/{receiptId}/status` 재호출.
- **statusStage**
  - `AUTO_PROCESSING`: OCR/자동 검증 중 → 2초 간격 권장.
  - `MANUAL_REVIEW`: 관리자 검토 대기 → 30초 간격 권장.
  - `DONE`: 최종 완료 → 폴링 중지.
- **reviewRequired === true**  
  - "검토 중입니다" 등 안내 표시.

---

## 6. FE 구현 시 참고

1. **폴링**: Complete 직후 status 호출 → `shouldPoll === true`이면 `recommendedPollIntervalMs` 후 재호출 → `shouldPoll === false` 또는 `statusStage === "DONE"`이면 중지.
2. **리워드**: `overall_status === "FIT"`일 때 `rewardAmount` 사용. 그 외는 `failReason`·`audit_trail` 및 **items[].error_code / error_message**로 사유 표시.
3. **장별 에러**: 결과 화면에서 `items[]`를 순회하며 `error_code`·`error_message`를 해당 이미지 옆에 표시하면 사용자가 어떤 장이 어떤 사유로 부적합/대기인지 파악하기 쉽습니다.
4. **이미지 URL**: `items[].image_url`은 MinIO object key. 실제 접근 URL이 필요하면 BE에서 presigned GET URL을 주는 별도 API가 있으면 해당 URL 사용.

---

## 7. 결과 콜백 (BE → FE)

- 콜백 URL은 BE 환경변수 `OCR_RESULT_CALLBACK_URL`로 지정합니다.
  - 운영: `https://easy.gwd.go.kr/dg/coupon/api/ocr/result`
  - 테스트: `http://210.179.205.50/dg/coupon/api/ocr/result`
- 분석 완료 시 BE가 해당 URL로 **POST 1회** 전송합니다.
- 재시도 정책: **없음** (실패/타임아웃 시 로그만 기록 후 종료).
- Body 규격:
  - `GET /api/v1/receipts/{receiptId}/status` 응답과 거의 동일
  - 콜백에서는 전송량 최적화를 위해 **`items[].ocr_raw`는 제외**
  - 추가 필드 `receiptId`(camelCase), `receipt_id`(snake_case) 포함 — 동일 UUID 값
  - 추가 필드 `userUuid`, `user_uuid` 포함(해당 신청의 사용자 UUID, 수신측 세션 매칭용)
  - 추가 필드 `schemaVersion` 포함
  - 추가 필드 `payloadMeta` 포함 (audit_trail / error_message 트렁케이트 여부 등)
- 인증:
  - 별도 인증 헤더 없음(운영 정책 기준)
  - 수신 측에서 `receiptId` 또는 `receipt_id` 존재 및 세션/DB와 일치하는지 검증 후 처리
- **"receiptId mismatching" 400 대응**: 수신 서버가 기대하는 ID는 presigned-url/complete 시 사용한 `receiptId`(UUID)와 동일해야 합니다. FE는 complete 요청 시 반드시 presigned에서 받은 `receiptId`를 그대로 사용하세요.

---

## 8. 결과 누락 복구 (FE 스케줄러)

- 네트워크 이슈 등으로 콜백을 받지 못한 건은 FE 스케줄러로 복구합니다.
- 복구 방식:
  1) FE에서 미완료 건 선별
  2) `GET /api/v1/receipts/{receiptId}/status` 호출
  3) 최종 상태 강제 동기화
- BE는 동일 `receiptId`에 대해 GET status 반복 호출을 허용하므로 스케줄러 복구 방식과 정합합니다.

---

## 9. 참고 문서

- 전체 흐름·유형: `FE_API_SPEC_EXTERNAL.md`
- 상세 스펙: `FE_API_SPEC_ONE_PAGE.md`
- 업종 분류/Gemini: `GEMINI_CLASSIFIER_GUIDE.md`

---

*문서 버전: 1.2 | GEMS OCR BE 기준*
