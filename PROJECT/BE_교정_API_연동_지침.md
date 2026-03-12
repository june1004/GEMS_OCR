# BE 연동을 위한 지침 – 데이터 교정 API

관리자 페이지에서 **「교정 사유 및 값 저장」** 클릭 시 FE는 **PATCH /api/v1/admin/submissions/:receiptId/correction** 을 호출합니다.  
이 레포의 백엔드(`backend/`)에는 해당 엔드포인트가 구현되어 있습니다. 배포 서버(예: api.nanum.online)에 반영·배포하고 **CORS** 설정이 필요합니다.

---

## 0. CORS 및 500 오류 시 확인 사항

로컬 FE(`http://localhost:8080`)에서 배포 BE(`https://api.nanum.online`)로 교정 API를 호출할 때 다음이 나올 수 있습니다.

| 현상 | 원인 | 조치 |
|------|------|------|
| **CORS policy blocked** + **500 Internal Server Error** | 1) 교정 라우트 미배포 또는 서버 내부 오류(500)<br>2) 500 응답 시 CORS 헤더가 붙지 않아 브라우저가 CORS 오류로 표시 | 1) 이 레포의 `PATCH …/correction` 라우트를 배포 서버에 반영<br>2) BE `main.py` 전역 예외 핸들러로 5xx도 JSON 반환해 CORS 적용<br>3) 배포 서버 환경 변수 **`CORS_ORIGINS=http://localhost:8080`** 설정 |

- 이 레포 BE는 `main.py`에서 전역 예외 핸들러를 두어 500 시에도 JSON + CORS가 적용되도록 되어 있습니다. 배포 시 동일 코드 적용이 필요합니다.

**500이 계속 날 때:** 배포 서버(api.nanum.online 등)에서 다음을 확인하세요.
- **이 레포의 교정 라우트가 배포되어 있는지** (`PATCH …/correction` 핸들러 포함 여부)
- **DB 스키마:** `submissions` 테이블에 `receipt_id`(UUID), `total_amount`(BIGINT) 컬럼이 있는지. `admin_audit_log` 테이블이 있으면 감사 로그까지 기록되며, **없어도** 교정 API는 200을 반환하도록 되어 있음(감사 로그만 스킵).
- **서버 로그:** 500 발생 시 백엔드 로그에 `correction: db error` 또는 `correction: unexpected error`가 남으므로, 해당 로그로 원인 확인.

---

## 1. 현재 FE 동작

| 구분 | 내용 |
|------|------|
| API 호출 | `PATCH /api/v1/admin/submissions/:receiptId/correction` (인증 헤더 포함) |
| 성공 시 | 로컬 캐시(localStorage) 저장 + 토스트 **"교정 데이터 저장됨"** / "서버에 반영되었습니다." |
| 실패 시 | **입력값은 항상 로컬에 저장.** 토스트 **"서버 전송 실패 · 로컬에 저장됨"** + 원인 안내(CORS/네트워크 오류 시 별도 문구, 그 외 API 에러 메시지). |
| localStorage 키 | `admin_correction_v1:{receiptId}` (API 성공 시 캐시, 실패 시에도 로컬 백업용 저장) |

---

## 2. BE API 사양 (이 레포에 구현됨)

이 레포의 `backend/`에는 아래 사양의 교정 API가 구현되어 있습니다. 배포 서버에 동일 코드를 반영하면 됩니다.

### 2.1 엔드포인트

| 항목 | 내용 |
|------|------|
| **메서드** | `PATCH` (또는 `PUT`) |
| **경로** | `/api/v1/admin/submissions/:receiptId/correction` |
| **대안** | `PUT /api/v1/receipts/:receiptId/sidecar` 등 (경로는 BE 정책에 맞게 조정 가능) |
| **인증** | 기존 Admin API와 동일 (Bearer / API Key 등) |

### 2.2 FE가 전송할 Request Body (연동 시)

FE가 로컬에 저장하는 구조와 동일한 필드를 API Body로 보냅니다.

```json
{
  "amount": "95727",
  "address": "36 Robinson Road City House #20-01 Singapore 068877",
  "reasonId": "err_ocr_amount",
  "reason_code": "ERR_OCR_AMOUNT",
  "reason_detail": "이미지 내 빛 반사·폰트 뭉개짐으로 AI가 숫자를 잘못 읽은 경우",
  "asset_tag": "RE_TRAINING_REQUIRED"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `amount` | string | N | 담당자가 확정한 금액(문자열). 빈 문자열이면 생략 가능. |
| `address` | string | N | 담당자가 확정한 가맹점 주소/지역. |
| `reasonId` | string | N | FE 수정 사유 프리셋 ID (예: `err_ocr_amount`, `other`). |
| `reason_code` | string | N | **Sidecar에 기록할 표준 코드** (예: `ERR_OCR_AMOUNT`, `USER_AMOUNT_MISTAKE`). [GEMS 표준 수정·반려 사유 분류](./GEMS_표준_수정_반려_사유_분류.md) 참고. |
| `reason_detail` | string | N | 사유 상세 설명(프리셋 설명 또는 사용자 입력). |
| `asset_tag` | string | N | **학습 데이터 분류용 태그** (예: `RE_TRAINING_REQUIRED`, `USER_ERROR_LABEL`, `LOW_QUALITY_SAMPLE`, `FRAUD_CHECK`). |

- `amount`는 FE에서 문자열로 다루며, BE에서 숫자로 파싱해 DB/Sidecar에 저장하면 됩니다.
- 수정 사유를 선택하지 않으면 `reason_code`, `reason_detail`, `asset_tag`는 없거나 빈 값으로 올 수 있습니다.

---

## 3. BE 기대 동작

1. **경로 파라미터**  
   - `receiptId`: 교정 대상 제출(영수증) ID (UUID).

2. **처리 내용**  
   - (선택) 해당 submission의 `total_amount`, `address` 등 DB 컬럼 업데이트.  
   - **Sidecar JSON**에 교정 이력 기록:
     - `human_correction.final_amount`, `human_correction.final_address`
     - `human_correction.reason_code`, `human_correction.reason_desc` (또는 `reason_detail`)
     - `human_correction.reviewed_by`, `human_correction.at` (수정자 ID, 시각)
     - `asset_tag` (학습 데이터 분류용)

3. **응답**  
   - 성공: `200 OK` + 본문 예: `{"receiptId": "<uuid>", "updated": true}`. 또는 `204 No Content`.  
   - 실패: `404`(submission 없음), `5xx`(서버 오류) — FE에서 토스트로 에러 메시지 표시.

4. **감사**  
   - 교정 API 호출 시 **수정자 ID, receiptId, 시각** 등 Audit Log 기록을 권장합니다.

### 3.1 이 레포 구현 요약

| 항목 | 동작 |
|------|------|
| submission 존재 확인 | `receipt_id::text = :rid`로 조회, 없으면 **404** |
| total_amount 업데이트 | `payload.amount`가 숫자로 파싱 가능하면 `submissions.total_amount` 갱신 |
| 감사 로그 | `admin_audit_log`에 `action='submission_correction'`, `after_json`에 payload 기록. **INSERT 실패 시** 로그만 남기고 요청은 **200 성공**으로 반환(테이블 없어도 500 아님). |
| 응답 | `200 OK` + `{"receiptId": "<receipt_id>", "updated": true}` |
| 예외 | DB 오류 시 `500` + `detail="Database error during correction"`, 기타 예외 시 `detail="Internal server error during correction"`. 서버 로그에 `correction: db error` / `correction: unexpected error` 기록. |

---

## 4. Sidecar JSON 구조 (참고)

보안 스토리지 등에 저장하는 Sidecar에는 아래와 같은 구조를 권장합니다.

```json
{
  "receipt_id": "c791b505-571d-444a-9f4e-d07c05780a0c",
  "ai_result": { "amount": 0, "confidence": 0.85 },
  "human_correction": {
    "final_amount": 95727,
    "final_address": "36 Robinson Road ...",
    "reason_code": "ERR_OCR_AMOUNT",
    "reason_desc": "이미지 내 빛 반사·폰트 뭉개짐으로 AI가 숫자를 잘못 읽은 경우",
    "reviewed_by": "admin@example.com",
    "at": "2026-03-05T12:00:00Z"
  },
  "asset_tag": "RE_TRAINING_REQUIRED"
}
```

- **reason_code** 값 목록은 [GEMS_표준_수정_반려_사유_분류.md](./GEMS_표준_수정_반려_사유_분류.md) 및 FE `correction-reasons.ts`와 맞추면, AI 재학습·분류 시 일관되게 사용할 수 있습니다.

---

## 5. 연동 체크리스트 (BE)

- [x] `PATCH /api/v1/admin/submissions/:receiptId/correction` — **이 레포에 구현됨**
- [x] Request Body에서 `amount`, `address`, `reasonId`, `reason_code`, `reason_detail`, `asset_tag` 수신 (`CorrectionIn` 스키마)
- [ ] Sidecar JSON(또는 동등 저장소)에 `human_correction`, `asset_tag` 기록 — 확장 시 참고(현재는 `admin_audit_log.after_json`에 payload 저장)
- [x] (선택) submission 테이블 `total_amount` 업데이트 — **구현됨** (amount 파싱 가능 시)
- [x] (권장) 교정 API 호출에 대한 Audit Log 기록 — **구현됨** (`admin_audit_log`, 실패 시에도 200 반환)
- [x] FE 연동: FE는 이미 해당 API를 호출함. BE 배포 및 `CORS_ORIGINS` 설정만 확인하면 됨.

---

## 6. API 서버(api.nanum.online) 환경 설정

교정 API를 배포한 뒤, **같은 버튼으로 서버 전송**이 되고 "서버에 반영되었습니다."가 나오려면, API 서버에서 **CORS**를 FE 주소로 허용해야 합니다.

### 6.1 등록할 환경 변수

| 환경 변수 | 설명 | 예시 |
|-----------|------|------|
| **CORS_ORIGINS** | API를 호출할 수 있는 프론트엔드 **Origin** 목록. 쉼표로 구분. | 아래 참고 |

- **Origin** = 브라우저가 요청을 보내는 페이지의 `프로토콜 + 호스트 + 포트` (예: `https://GEMS.nanum.online`, `http://localhost:8080`).
- 이 레포 BE는 `CORS_ORIGINS`가 **비어 있으면** 기본 목록(`http://localhost:8080`, `http://169.254.240.5:8080`)을 사용하고, **값이 있으면 해당 값으로 완전히 대체**합니다. 따라서 로컬과 운영을 모두 쓰려면 허용할 origin을 **전부** 나열해야 합니다.

### 6.2 설정 예시

| 상황 | CORS_ORIGINS 값 |
|------|------------------|
| **현재: 로컬 FE만** (http://localhost:8080에서 api.nanum.online 호출) | `http://localhost:8080` |
| **향후: FE를 GEMS.nanum.online에 배포** (https://GEMS.nanum.online에서 API 호출) | `https://GEMS.nanum.online` |
| **로컬 + 운영 동시 허용** | `http://localhost:8080,https://GEMS.nanum.online` |

- 프로토콜(`http` / `https`), 호스트, 포트까지 **실제 FE URL과 동일**하게 적어야 합니다. 끝에 `/` 없이.
- 예: FE가 `https://GEMS.nanum.online` 이면 `https://GEMS.nanum.online` 만 추가. `https://GEMS.nanum.online/` (슬래시 있음)은 다른 origin으로 인식될 수 있으므로 권장하지 않습니다.

### 6.3 정리

- **지금(localhost):** API 서버에 `CORS_ORIGINS=http://localhost:8080` 설정 → 같은 버튼으로 서버 전송 시 "서버에 반영되었습니다." 동작.
- **나중에(GEMS.nanum.online):** FE 배포 URL이 정해지면 해당 origin을 `CORS_ORIGINS`에 추가. 로컬도 계속 쓰려면 `http://localhost:8080,https://GEMS.nanum.online` 처럼 쉼표로 함께 등록.

### 6.4 트러블슈팅: "서버 전송 실패 • 로컬에 저장됨" / CORS / 500

**증상:** 저장 클릭 시 "CORS/네트워크 오류로 서버에 보내지 못했습니다" 또는 브라우저 콘솔에  
`Access to fetch ... has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header` + `500 (Internal Server Error)`.

**원인:** 서버(api.nanum.online)에서 **먼저 500**이 나고, 그 500 응답에 CORS 헤더가 없어서 브라우저가 CORS 오류로 막습니다. 즉, **근본 원인은 500**이고, CORS는 그 결과로 보이는 현상입니다.

**배포 서버에서 확인할 것**

| 순서 | 확인 항목 | 조치 |
|------|-----------|------|
| 1 | **이 레포(GEMS_OCR) 최신 코드 배포** | `PATCH /api/v1/admin/submissions/{receiptId}/correction` 라우트와 전역 예외 핸들러가 포함된 버전으로 배포. 이 레포의 main.py는 500 발생 시에도 JSON으로 응답해 CORS가 붙도록 되어 있음. |
| 2 | **CORS_ORIGINS** | `CORS_ORIGINS=http://localhost:8080` 설정 후 서버 재시작. |
| 3 | **500 원인 확인** | 500 응답이 `{"detail":"Internal server error","receiptId":"..."}` 형태면 **최신 코드가 배포된 상태**. 서버 로그에서 **반드시** 아래로 검색해 실제 예외 메시지 확인: `Correction API error (receiptId=` 또는 `Correction commit failed (receiptId=`. **흔한 원인:** (1) `submission_sidecar` 컬럼 없음 → `PROJECT/migrations/submission_sidecar_correction.sql` 적용, (2) `submissions.audit_trail`/`audit_log` 컬럼 없음 → `PROJECT/migrations/submission_audit_columns.sql` 적용, (3) `admin_audit_log` 테이블 없음(이 경우에도 교정 저장은 200 성공·감사 로그만 경고), (4) DB 연결/타임아웃. |

이 레포 기준으로 교정 API는 (1) 요청 본문을 raw JSON으로 수락해 검증 실패(422) 가능성을 줄였고, (2) 예외 시 500도 `{"detail":"Internal server error","receiptId":"..."}` 형태로 JSON 반환하므로 CORS 헤더가 붙습니다. **동일 코드가 배포되어 있으면** 500이 나더라도 CORS로 막히지 않고, FE에서 receiptId를 활용해 사용자에게 안내할 수 있습니다. 여전히 CORS만 보인다면 배포 버전이 다르거나, 리버스 프록시/API 게이트웨이에서 500을 직접 반환하는 경우일 수 있습니다.

---

## 7. 관련 문서

- [백엔드_요청사항_정리.md](./백엔드_요청사항_정리.md) – **섹션 10** (데이터 교정 및 Sidecar)
- [GEMS_표준_수정_반려_사유_분류.md](./GEMS_표준_수정_반려_사유_분류.md) – reason_code·asset_tag 표준 값
