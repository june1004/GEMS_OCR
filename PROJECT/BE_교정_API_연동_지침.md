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

---

## 1. 현재 FE 동작

| 구분 | 내용 |
|------|------|
| API 호출 | `PATCH /api/v1/admin/submissions/:receiptId/correction` (인증 헤더 포함) |
| 성공 시 | 로컬 캐시(localStorage) 저장 + 토스트 "서버에 반영되었습니다." |
| 실패 시 | 토스트 "저장 실패" + 에러 메시지 (CORS/500이면 브라우저에서 네트워크 오류로 표시) |
| localStorage 키 | `admin_correction_v1:{receiptId}` (API 성공 후 캐시용) |

---

## 2. BE에서 구현할 API

### 2.1 엔드포인트 (권장)

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
   - 성공: `200 OK` 또는 `204 No Content`.  
   - 실패: `4xx`/`5xx` + FE에서 토스트 등으로 에러 메시지 표시 가능하도록 메시지 포함 권장.

4. **감사**  
   - 교정 API 호출 시 **수정자 ID, receiptId, 시각** 등 Audit Log 기록을 권장합니다.

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

- [ ] `PATCH /api/v1/admin/submissions/:receiptId/correction` (또는 동일 역할의 경로) 구현
- [ ] Request Body에서 `amount`, `address`, `reason_code`, `reason_detail`, `asset_tag` 수신
- [ ] Sidecar JSON(또는 동등 저장소)에 `human_correction`, `asset_tag` 기록
- [ ] (선택) submission 테이블 `total_amount`, 주소 등 업데이트
- [ ] (권장) 교정 API 호출에 대한 Audit Log 기록
- [ ] FE 연동: BE 배포 후 FE에서 해당 API 호출로 전환 (localStorage 저장과 병행 또는 대체)

---

## 6. 관련 문서

- [백엔드_요청사항_정리.md](./백엔드_요청사항_정리.md) – **섹션 10** (데이터 교정 및 Sidecar)
- [GEMS_표준_수정_반려_사유_분류.md](./GEMS_표준_수정_반려_사유_분류.md) – reason_code·asset_tag 표준 값
