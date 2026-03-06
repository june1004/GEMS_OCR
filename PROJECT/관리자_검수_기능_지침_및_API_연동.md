# 관리자 검수 기능 지침 및 API 연동

> 담당자가 **관리 페이지**에서 **입력폼(FE 데이터)·영수증 이미지·인식된 정보(OCR)** 를 확인하고 검수할 수 있도록 하는 기능 지침과, 관리자 페이지–백엔드 연동을 위한 **API 명세**를 정리한 문서입니다.

---

## 1. 목적 및 검수 플로우

### 1.1 목적

- **입력폼**: FE에서 Complete 시 제출한 폼 데이터(`data.items[]`)를 확인한다.
- **영수증 이미지**: 업로드된 증빙 이미지가 정상인지, 영수증/OTA 등이 맞는지 육안 확인한다.
- **인식된 정보**: OCR로 추출된 상호·사업자번호·금액·결제일·주소 등이 올바른지 확인한다.
- **검수**: 위 세 가지를 비교한 뒤, 수동 판정(Override) 및 FE에 결과 전달(콜백)을 수행한다.

### 1.2 검수 대상 상태

- **수동 검토 필요**: `PENDING_NEW`, `PENDING_VERIFICATION`, `VERIFYING`
- **종결 후 재검토/콜백**: `FIT`, `UNFIT` 등 (필요 시 Override·콜백 재전송)

### 1.3 담당자 검수 절차(권장)

1. **신청 목록**에서 `receiptId` 또는 상태 필터로 검수 대상 건 조회
2. **신청 상세** 진입 후 **3열 레이아웃**으로 동시 확인  
   - 좌: 영수증 이미지  
   - 중: OCR 인식 결과(장별)  
   - 우: FE 입력 스냅샷 + 검수 액션
3. **확인 사항**  
   - FE 입력이 존재하는지, 장 순서가 이미지/OCR과 맞는지  
   - 이미지가 정상 노출되는지(깨짐·다른 파일 업로드 여부)  
   - OCR 핵심 필드(상호·사업자번호·주소·금액·결제일)가 채워졌는지, `error_code`/`confidence` 확인  
   - 수동 보정이 필요하면 **Override**로 최종 판정(FIT/UNFIT) + 사유 입력
4. **검수 완료 시**  
   - Override 시 **콜백 자동 송출(resend_callback=true)** 권장  
   - 필요 시 **콜백 검증** 버튼으로 즉시 전송 테스트  
   - **콜백 로그**로 실제 송출 이력 확인

---

## 2. 화면 구성 권장 (3열)

| 영역 | 표시 내용 | 데이터 소스(API) |
|------|-----------|------------------|
| **좌: 증빙 이미지** | 장별 썸네일·확대 보기, doc_type(RECEIPT/OTA_INVOICE) | `GET .../admin/receipts/{receiptId}/images` |
| **중: OCR 인식 결과** | 장별 status, error_code, error_message, confidence, store_name, biz_num, address, pay_date, amount, card_num, (선택) ocr_raw | `GET .../admin/submissions/{receiptId}` → `statusPayload.items[]` |
| **우: FE 입력 + 액션** | FE 제출 폼 스냅샷(user_input_snapshot), 장별 비교, Override/콜백 버튼 | `GET .../admin/submissions/{receiptId}` → `submission.user_input_snapshot`, Override/콜백 API |

### 2.1 장(Item) 인덱스 매칭

- **이미지** `items[i]` ↔ **OCR** `statusPayload.items[i]` ↔ **FE 입력** `user_input_snapshot.items[i]`  
- 매칭 키: **순서(인덱스)** 및 필요 시 **item_id** (OCR/상세 응답의 `item_id`와 이미지 응답의 `item_id`로 동일 장 연결).

### 2.2 카드번호 표기 규칙(OCR·FE 해석)

- `0000` → "현금"
- `1000` → "카드번호 없음/****"
- 그 외 4자리 → "****-****-****-1234" 등으로 표기

---

## 3. 관리자 페이지 연동 API 명세

### 3.1 인증

- **헤더**
  - `X-Admin-Key`: 환경변수 `ADMIN_API_KEY`와 일치해야 함 (설정된 경우)
  - `X-Admin-Actor`: 담당자 식별자(감사 로그에 저장)
- 미설정 시 인증 생략 가능(개발 환경 등). 운영 환경에서는 반드시 설정 권장.

---

### 3.2 신청 목록 검색

| 항목 | 내용 |
|------|------|
| **Method** | `GET` |
| **Path** | `/api/v1/admin/submissions` |
| **Query** | `status`, `userUuid`, `receiptId`, `dateFrom`, `dateTo`, `limit`(기본 50, 1~200), `offset`(기본 0) |
| **Response** | `{ "total": number, "items": [ { "receiptId", "userUuid", "project_type", "status", "total_amount", "created_at" } ] }` |
| **용도** | 검수 대상 목록 조회, receiptId/상태/기간 필터 |

---

### 3.3 신청 단건 상세 (입력폼 + 인식 정보)

| 항목 | 내용 |
|------|------|
| **Method** | `GET` |
| **Path** | `/api/v1/admin/submissions/{receiptId}` |
| **Response** | `{ "receiptId", "submission": { "submission_id", "user_uuid", "project_type", "campaign_id", "status", "total_amount", "global_fail_reason", "fail_reason", "audit_trail", "created_at", **"user_input_snapshot"** }, "statusPayload": { "submission_id", "project_type", "overall_status", "total_amount", "global_fail_reason", "items": [ { **"item_id"**, "status", "error_code", "error_message", "extracted_data": { "store_name", "amount", "pay_date", "address", "card_num" }, "image_url", **"ocr_raw"** (관리자용만 포함) }, ... ], "audit_trail", "shouldPoll", "reviewRequired", "statusStage", "payloadMeta" } }` |
| **용도** | 상세 화면의 **FE 입력(user_input_snapshot)** 과 **OCR 인식 결과(statusPayload.items[])** 표시, 장별 비교 |

**user_input_snapshot** 구조(방식2 기준):  
- `items`: 배열. 각 요소는 FE가 제출한 장별 폼 데이터(예: amount, payDate, location, storeName 등).  
- 인덱스 `i` = `statusPayload.items[i]`, 이미지 `items[i]`와 같은 장.

---

### 3.4 신청 영수증 이미지

| 항목 | 내용 |
|------|------|
| **Method** | `GET` |
| **Path** | `/api/v1/admin/receipts/{receiptId}/images` |
| **Response** | `{ "receiptId", "expiresIn": 600, "items": [ { "item_id", "doc_type", "image_key", "image_url" (presigned GET URL, 10분 유효) } ] }` |
| **용도** | 상세 화면 **좌측 이미지 패널**. `image_url`을 그대로 img src로 사용. |

---

### 3.5 검수 완료(수동 판정 변경)

| 항목 | 내용 |
|------|------|
| **Method** | `POST` |
| **Path** | `/api/v1/admin/submissions/{receiptId}/override` |
| **Body** | `{ "status": "FIT" | "UNFIT", "reason": "사유 문자열", "override_reward_amount": number (선택), "resend_callback": boolean (기본 false, **검수 완료 시 true 권장**) }` |
| **Response** | `{ "receiptId", "previous_status", "new_status", "updated_at" }` |
| **용도** | 담당자가 입력폼·이미지·OCR 확인 후 **최종 판정** 적용. `resend_callback=true` 시 FE 콜백 URL로 결과 즉시 재전송. |

---

### 3.6 콜백 검증(즉시 송출)

| 항목 | 내용 |
|------|------|
| **Method** | `POST` |
| **Path** | `/api/v1/admin/submissions/{receiptId}/callback/verify` |
| **Body** | 없음 |
| **Response** | `{ "ok", "status", "elapsed_ms", "url", "skipped", "reason" 등 }` (실제 전송 결과) |
| **용도** | 현재 DB 기준 상태를 콜백 URL로 **즉시 전송**하고 결과를 화면에 표시. 설정 여부·수동 재전송 테스트용. |

---

### 3.7 콜백 전송 로그 조회

| 항목 | 내용 |
|------|------|
| **Method** | `GET` |
| **Path** | `/api/v1/admin/submissions/{receiptId}/callback/logs` |
| **Query** | `limit` (기본 20, 1~200) |
| **Response** | `{ "receiptId", "items": [ { "id", "action": "CALLBACK_SEND"|"CALLBACK_RESEND"|"CALLBACK_VERIFY", "actor", "created_at", "meta" } ] }` |
| **용도** | 해당 건의 콜백 송출 이력 표시. `CALLBACK_SEND.meta.ok` 등으로 성공 여부 확인. |

---

### 3.8 콜백 재전송(직접 호출)

| 항목 | 내용 |
|------|------|
| **Method** | `POST` |
| **Path** | `/api/v1/admin/submissions/{receiptId}/callback/resend` |
| **Body** | `{ "target_url": "https://..." }` (선택. 없으면 환경변수 OCR_RESULT_CALLBACK_URL 사용) |
| **Response** | `{ "receiptId", "sent": true }` |
| **용도** | Override 없이 **콜백만 다시 보낼 때** 사용. 검수 완료는 Override + resend_callback 로 처리 권장. |

---

## 4. API 호출 순서 예시(상세 화면)

1. `GET /api/v1/admin/submissions?receiptId={id}` 또는 목록에서 `receiptId` 확보  
2. 상세 진입 시 **동시 요청**  
   - `GET /api/v1/admin/submissions/{receiptId}` → FE 입력·OCR 결과  
   - `GET /api/v1/admin/receipts/{receiptId}/images` → 이미지 URL 목록  
3. 검수 완료 시  
   - `POST /api/v1/admin/submissions/{receiptId}/override` (status, reason, resend_callback)  
4. (선택) 콜백 확인  
   - `POST .../callback/verify` → 즉시 송출 테스트  
   - `GET .../callback/logs?limit=20` → 이력 표시  

---

## 5. 운영자가 꼭 확인할 4가지(체크리스트)

1. **FE 입력(user_input_snapshot)** 이 있는지, 장별 입력이 이미지/OCR 순서와 맞는지  
2. **이미지**가 정상 렌더링되는지(깨짐·잘못된 파일 업로드 여부)  
3. **OCR 핵심 필드**(상호·사업자번호·주소)가 비어 있지 않은지, **confidence**·**error_code**(예: OCR_004) 확인  
4. **콜백**이 실제 송출되었는지 (`callback/logs` 의 `CALLBACK_SEND`/`CALLBACK_RESEND` meta 확인)  

---

## 6. 참고 문서

- **화면 레이아웃·UI 요소**: `관리자_페이지_화면설계안.md`  
- **추가 개발 반영 사항**: `관리자_페이지_추가_개발_지침.md`  
- **status/error_code 정리**: `status_error_code_정책.md`  
- **API 상세(Swagger)**: 서버 `/docs` (Admin - Submissions, Admin - Callback 태그)
