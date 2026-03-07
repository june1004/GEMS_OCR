# admin_audit_log 보강 및 인식률 활용

> 관리자 감사로그(`admin_audit_log`)를 분석·보강하여 **운영 추적**과 **인식률(분류 정확도) 개선**에 활용하는 방안을 정리합니다.

---

## 1. 현재 기록되는 액션

| action | target_type | 용도 |
|--------|-------------|------|
| `RULE_UPDATE` | judgment_rule_config | 판정 규칙 변경 이력 |
| `CANDIDATE_APPROVE` | unregistered_store | 후보 상점 마스터 편입(승인) |
| `SUBMISSION_OVERRIDE` | submission | 수동 판정 변경(override) |
| `CALLBACK_SEND` | submission | 콜백 전송 시도(성공/실패) |
| `CALLBACK_RESEND` | submission | 콜백 재전송 |
| `CALLBACK_VERIFY` | submission | 관리자 콜백 검증(즉시 송출) |
| `CAMPAIGN_CREATE` | campaign | 캠페인 생성 |
| `CAMPAIGN_UPDATE` | campaign | 캠페인 수정 |

---

## 2. 보강된 항목 (인식률·피드백용)

### 2.1 CANDIDATE_APPROVE

- **before_json**에 `predicted_category` 추가  
  → 시스템이 예측한 업종을 승인 전 상태로 보존.
- **meta**에 다음 필드 추가:
  - `predicted_category`: 자동 분류 결과(룰/Gemini).
  - `target_category`: 관리자가 최종 선택한 업종.
  - `corrected`: `predicted_category != target_category` 이면 `true`, 같으면 `false`, 예측 없으면 `null`.

**활용**:  
- `corrected = true` 인 건만 조회하면 “관리자가 고친 케이스”로 모을 수 있음.  
- 이 데이터를 **whitelist 키워드 추가** 또는 **Gemini 프롬프트/파인튜닝**에 활용하면 인식률 개선에 사용 가능.

### 2.2 감사로그 목록 API

- **GET** `/api/v1/admin/audit-log`
  - **Query**: `action`, `target_type`, `from`, `to`, `include_json`, `limit`
  - **Response**: `total`, `items[]` (id, action, target_type, target_id, actor, created_at, meta[, before_json, after_json])
  - `include_json=true` 시 before/after 전체 포함(용량 주의).

**활용**:  
- 인식률 분석: `action=CANDIDATE_APPROVE` + `meta->corrected = true` 인 건을 기간별로 집계.  
- 콜백 이슈 추적: `action=CALLBACK_SEND` + `meta->ok = false` 필터.  
- 규칙 변경 이력: `action=RULE_UPDATE` 조회.

---

## 3. 인식률 개선에 쓰는 방법

1. **정확도 지표**  
   - 기간별로 `CANDIDATE_APPROVE` 건수 중 `meta.corrected === true` 비율을 계산.  
   - 비율이 높으면 자동 분류(룰/Gemini)가 자주 틀린 것이므로, whitelist 확장·Gemini 튜닝 대상.
2. **피드백 데이터 수집**  
   - `corrected = true` 인 로그에서 `before_json.store_name`, `address`, `meta.target_category`를 추출.  
   - TOUR_FOOD 등 목적별로 모아서:
     - whitelist에 패턴 추가하거나,
     - Gemini few-shot/파인튜닝용 데이터로 사용.
3. **콜백 안정성**  
   - `CALLBACK_SEND` 중 `meta.ok = false` 건을 주기적으로 조회해 URL/타임아웃/에러 메시지 패턴을 점검.

---

## 4. 추후 확장(선택)

- **CLASSIFY_ATTEMPT** (또는 **OCR_ITEM_RESULT**)  
  - 자동 분류/OCR 수행 시 메타데이터만 간단히 기록(예: receipt_id, item_id, predicted_category, confidence, classifier_type).  
  - 전량 로깅은 부하·용량 부담이 있으므로, “AI 사용 건” 또는 “confidence < 0.7” 등 일부만 샘플링하는 방안 검토.
- **인덱스**  
  - 분석 쿼리가 많아지면 `(action, created_at)` 또는 `(target_type, action)` 복합 인덱스 추가 검토.
- **통계 API**  
  - `GET /api/v1/admin/audit-log/stats?from=...&to=...` 로 기간별 액션 건수, `CANDIDATE_APPROVE` 중 corrected 비율 등을 집계해 대시보드에 연동.

---

*문서 버전: 1.0 | GEMS OCR BE 기준*
