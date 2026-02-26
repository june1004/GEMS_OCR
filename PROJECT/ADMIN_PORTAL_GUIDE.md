# 관리자 웹 연동 가이드 (gems_ocr-9f4d37f5 + FastAPI)

> 목적: 관리자 웹에서 **판정 규칙 운영**과 **신규 상점 후보군 자산화**를 실제 운영 가능하게 연결하기 위한 체크리스트/설계 지침.

---

## 빠른 목차

- **0. 이미 구현된 관리자 기능**: 지금 당장 연동 가능
- **1. 관리자 웹 MVP 화면**: 규칙 설정 + 후보 상점 승인 + 증거 확인
- **2. 운영 보강 기능(설계)**: submission 검색/override/콜백 재전송/이미지 presigned GET
- **3. 보안/감사/운영**: 관리자 인증, 감사로그, 장애 대응
- **4. 콜백/상태 스키마**: schemaVersion v2, payloadMeta, 트렁케이트

---

## 0. 현재 BE에서 “이미 구현된 관리자 기능”

### A) 판정 규칙 운영(싱글톤 설정)

- **설정 테이블**: `judgment_rule_config` (id=1 싱글톤)
- **마이그레이션**: `PROJECT/migrations/judgment_rule_config.sql`
- **관리자 API**
  - `GET /api/v1/admin/rules/judgment` (조회)
  - `PUT /api/v1/admin/rules/judgment` (수정)

관리 가능한 규칙(현재 반영됨):
- **unknown_store_policy**: `AUTO_REGISTER | PENDING_NEW`
  - `PENDING_NEW`: 마스터 미등록 상점은 무조건 `PENDING_NEW`로 대기
  - `AUTO_REGISTER`: 분류 신뢰도 임계치 이상이면 자동 마스터 편입 후 재매칭(FIT 가능)
- **auto_register_threshold**: 자동 편입 임계치 (0.0~1.0)
- **enable_gemini_classifier**: 신규 상점 분류 시 Gemini 사용 여부
- **min_amount_stay / min_amount_tour**: 최소 금액

#### API 예시

##### (1) 조회

`GET /api/v1/admin/rules/judgment`

Response 예시:

```json
{
  "unknown_store_policy": "AUTO_REGISTER",
  "auto_register_threshold": 0.9,
  "enable_gemini_classifier": true,
  "min_amount_stay": 60000,
  "min_amount_tour": 50000,
  "updated_at": "2026-02-26T03:10:00.000000"
}
```

##### (2) 수정

`PUT /api/v1/admin/rules/judgment`

Request 예시:

```json
{
  "unknown_store_policy": "PENDING_NEW",
  "auto_register_threshold": 0.95,
  "enable_gemini_classifier": false,
  "min_amount_stay": 60000,
  "min_amount_tour": 50000
}
```

Response는 조회와 동일 구조로 갱신값 반환.

#### 화면 UX 권장사항

- **저장 버튼 클릭 시**: “저장됨(적용 시각: updated_at)” 토스트 + 상단에 “해당 시점 이후 신규 분석 건부터 적용” 안내.
- **정책 변경 위험도 표시**:
  - `AUTO_REGISTER` + 낮은 threshold는 오등록 위험 상승
  - `PENDING_NEW`는 자동화율 감소(관리자 업무 증가)

---

### B) 신규 상점 후보군 관리

- **후보 테이블**: `unregistered_stores`
- **관리자 API**
  - `GET /api/v1/admin/stores/candidates`
    - Query: `city_county`, `min_occurrence`, `sort_by=occurrence_count|created_at`
    - `TEMP_VALID`, `AUTO_REGISTERED` 포함 노출(검토/감사 목적)
  - `POST /api/v1/admin/stores/candidates/approve`
    - 선택 후보를 `master_stores`로 편입(자산화)

#### API 예시

##### (1) 후보 목록 조회

`GET /api/v1/admin/stores/candidates?sort_by=occurrence_count&min_occurrence=3&city_county=춘천시`

Response 예시:

```json
{
  "total_candidates": 2,
  "items": [
    {
      "candidate_id": "cand_98765",
      "store_name": "강원감자옹심이 전문점",
      "biz_num": "123-45-67890",
      "address": "강원특별자치도 춘천시 중앙로 123",
      "tel": "033-123-4567",
      "occurrence_count": 15,
      "predicted_category": "TOUR_FOOD",
      "first_detected_at": "2026-02-10T14:30:00",
      "recent_receipt_id": "90370b26-d947-43f0-a62b-aeeaee5666de",
      "status": "PENDING_REVIEW"
    }
  ]
}
```

##### (2) 후보 승인(마스터 편입)

`POST /api/v1/admin/stores/candidates/approve`

Request 예시:

```json
{
  "candidate_ids": ["cand_98765"],
  "target_category": "TOUR_SIGHTSEEING",
  "is_premium": false
}
```

Response 예시:

```json
{
  "approved_count": 1,
  "failed_ids": []
}
```

#### 화면 UX 권장사항

- **빈도순(occurrence_count desc)** 기본 정렬 고정(자동화율을 빨리 올리는 데 가장 효과적)
- 각 후보 row에 “증거 보기” 버튼:
  - `recent_receipt_id`로 해당 신청의 이미지/상세를 확인할 수 있어야 운영자가 신뢰하고 승인 가능

---

## 1. 관리자 웹에서 반드시 구현해야 할 화면/기능 (MVP)

### 1) “판정 규칙” 설정 화면

#### 화면 요소(권장)
- **미등록 상점 처리 정책** 토글: `PENDING_NEW` ↔ `AUTO_REGISTER`
- **자동 편입 임계치** 슬라이더(0.0~1.0)
- **Gemini 분류 사용** ON/OFF
- **최소 금액** (STAY/TOUR) 입력
- 저장/적용 버튼 + “최근 변경 시각(updated_at)” 표시

#### 연동 API
- 초기 로딩: `GET /api/v1/admin/rules/judgment`
- 저장: `PUT /api/v1/admin/rules/judgment`

> 운영 팁: 저장 성공 시 관리자 화면에 “해당 시점부터 신규 분석 건에 적용” 안내 문구를 보여주세요. (이미 분석 완료된 건에는 소급 적용되지 않음)

---

### 2) “신규 상점 후보군” 리스트 화면

#### 화면 요소(권장)
- 필터:
  - 시군구(`city_county`)
  - 최소 발견 횟수(`min_occurrence`)
  - 정렬: 빈도순(기본) / 최신순
- 리스트 컬럼:
  - 상호명, 사업자번호(biz_num), 주소, 전화번호(tel)
  - 발생 빈도(occurrence_count)
  - predicted_category / category_confidence / classifier_type (있을 때)
  - 최근 증거 receiptId(recent_receipt_id)
  - 상태(`TEMP_VALID` / `AUTO_REGISTERED`)
- 액션:
  - **선택 승인** → master_stores 편입 (approve API)
  - “증거 보기” (recent_receipt_id로 영수증 이미지/상세 조회)

#### 연동 API
- 리스트: `GET /api/v1/admin/stores/candidates`
- 승인: `POST /api/v1/admin/stores/candidates/approve`

---

### 3) “증거(영수증) 확인” 기능(최소)

현재 BE에는 “이미지 presigned GET URL 발급” 전용 API가 없습니다.  
관리자 웹은 아래 중 하나를 선택해야 합니다.

- **옵션 A(권장)**: BE에 `GET /api/v1/admin/receipts/{receiptId}/images` 같은 presigned GET API를 추가해, 관리자 웹은 해당 URL로 이미지를 보여줌
- **옵션 B**: 운영 환경에서 스토리지 접근 정책을 별도로 마련(비권장: 보안/권한 통제가 어려움)

#### 옵션 A(권장) API 설계 초안 (미구현)

- `GET /api/v1/admin/receipts/{receiptId}/images`
  - Response:

```json
{
  "receiptId": "uuid",
  "items": [
    {
      "item_id": "uuid",
      "image_key": "receipts/....jpg",
      "image_url": "https://presigned-get-url..."
    }
  ]
}
```

- 구현 포인트:
  - MinIO `get_object`용 presigned URL 발급
  - 만료시간(예: 5~10분)
  - 관리자 인증 필요

---

## 2. 운영을 위해 관리자 웹에서 “추가 구현을 강력 권장”하는 기능

### A) Submission 검색/조회(운영 CS 필수)

관리자 웹에서 자주 필요한 조회:
- receiptId로 검색
- 사용자(userUuid)로 검색
- 상태별 필터(FIT/UNFIT/PENDING_NEW 등)
- 기간(created_at) 필터
- items 단위 판정/에러코드 확인

이를 위해 BE에 아래 API 신설이 필요합니다(현재 미구현):
- `GET /api/v1/admin/submissions?status=&from=&to=&userUuid=&receiptId=`
- `GET /api/v1/admin/submissions/{receiptId}` (status payload와 동일 스냅샷 + 내부 필드)

#### API 설계 초안 (미구현)

##### (1) 목록 검색

`GET /api/v1/admin/submissions?status=PENDING_NEW&from=2026-02-01&to=2026-02-29&limit=50&offset=0`

Response 예시:

```json
{
  "total": 125,
  "items": [
    {
      "receiptId": "uuid",
      "userUuid": "user-uuid",
      "project_type": "TOUR",
      "status": "PENDING_NEW",
      "total_amount": 0,
      "created_at": "2026-02-26T02:00:00"
    }
  ]
}
```

##### (2) 단건 상세

`GET /api/v1/admin/submissions/{receiptId}`

Response는 기본적으로 `GET /api/v1/receipts/{receiptId}/status` payload + 관리자용 내부 필드(예: campaign_id, raw DB timestamps 등).

---

### B) “수동 판정 변경(override)” 워크플로우

요구 예시: `UNFIT → FIT`로 관리자 검토 후 상태 변경.

권장 설계:
- `POST /api/v1/admin/submissions/{receiptId}/override`
  - body: `status`, `reason`, (optional) `override_reward_amount`
- BE는:
  - submission.status/fail_reason/audit_trail 갱신
  - 필요한 경우 items[] 상태도 함께 갱신
  - 변경 감사로그 기록(누가/언제/무엇을)
  - **콜백 재전송 옵션** 제공(선택)

#### API 설계 초안 (미구현)

`POST /api/v1/admin/submissions/{receiptId}/override`

Request 예시:

```json
{
  "status": "FIT",
  "reason": "관리자 검토 승인",
  "override_reward_amount": 10000,
  "resend_callback": true
}
```

Response 예시:

```json
{
  "receiptId": "uuid",
  "previous_status": "PENDING_NEW",
  "new_status": "FIT",
  "updated_at": "2026-02-26T03:20:00"
}
```

> 운영 정책: override는 반드시 감사로그 남기기(누가/왜/무엇을 변경).

---

### C) 콜백 재전송(장애 대응)

콜백이 실패했거나 FE가 누락한 경우를 대비해:
- `POST /api/v1/admin/submissions/{receiptId}/callback/resend`
- BE는 DB에 저장된 최종 payload를 재구성해 콜백 URL로 POST(재시도 정책은 운영 정책에 맞춰 결정)

#### API 설계 초안 (미구현)

`POST /api/v1/admin/submissions/{receiptId}/callback/resend`

Request 예시:

```json
{
  "target_url": "https://easy.gwd.go.kr/dg/coupon/api/ocr/result"
}
```

Response 예시:

```json
{
  "receiptId": "uuid",
  "sent": true,
  "http_status": 200
}
```

---

## 3. FastAPI 서버 운영/관리 지침 (보강 권장)

### 1) 관리자 API 보호(필수)

현재 `/api/v1/admin/*`는 **인증/권한 체크가 없습니다.** 운영 전 반드시 보호하세요.

권장 옵션:
- **Reverse proxy 단에서 Basic Auth / IP allowlist**
- **JWT 기반 관리자 인증**(역할: ADMIN)
- 최소한 “관리자 전용 도메인 + 네트워크 차단” 적용

#### 권장 운영안(현실적인 1단계)

- 관리자 웹과 FastAPI를 **같은 사설망/VPN**에 두고
- Reverse proxy에서
  - `/api/v1/admin/*` 경로만 **IP allowlist**
  - 또는 **Basic Auth**

> 이유: FastAPI 코드 수정 없이도 빠르게 안전성을 확보 가능.

---

### 2) 감사로그(Audit Log) 테이블 도입(권장)

규칙 변경/수동 override/후보 승인 등은 모두 “결정”이므로 기록이 필요합니다.

권장 테이블 예:
- `admin_audit_log` (id, actor, action, target_id, before_json, after_json, created_at)

#### 감사로그에 남겨야 하는 이벤트(최소)

- 판정 규칙 변경(`PUT /admin/rules/judgment`)
- 후보 상점 승인(`POST /admin/stores/candidates/approve`)
- override(수동 판정 변경)
- 콜백 재전송

> 운영 리스크(민원/정산)를 줄이려면 “누가 어떤 근거로 바꿨는지”를 남겨야 합니다.

---

### 3) 운영 환경변수 체크리스트

필수:
- `DATABASE_URL`
- `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`
- `NAVER_OCR_INVOKE_URL`, `NAVER_OCR_SECRET`

옵션(기능 활성화):
- `OCR_RESULT_CALLBACK_URL` (콜백 목적지)
- `GEMINI_API_KEY` (AI 분류)
- `OCR_CALLBACK_MAX_AUDIT_TRAIL_CHARS`, `OCR_CALLBACK_MAX_ERROR_MESSAGE_CHARS` (콜백 최적화)

---

## 4. 데이터 정규화(표시/자산화 품질)

BE 저장 시점에 정규화:
- 결제일: `YYYY/MM/DD`
- 사업자번호: `000-00-00000`
- 전화번호: 하이픈 포맷
- 주소: 공백 정리, `강원도 → 강원특별자치도`

기존 데이터 백필:
- `PROJECT/migrations/normalize_asset_fields.sql`

---

## 5. 콜백/상태 스키마(관리자 웹에서 알아야 할 변경점)

### 5-1. 콜백 payload 최적화

- 콜백 payload는 GET status와 “거의 동일”하지만, **대용량 필드 `items[].ocr_raw`는 콜백에서 제외**됩니다.
- `schemaVersion`이 포함되며, 현재 값은 **2**입니다.
- `payloadMeta`가 포함됩니다:
  - `auditTrailTruncated`: audit_trail 트렁케이트 여부
  - `errorMessageTruncatedCount`: item error_message 트렁케이트된 개수
  - `generatedAt`: 생성 시각

관리자 웹/운영 시스템은:
- **콜백을 받은 payload만으로도 판정(상태/금액/리워드/사유)을 표시**할 수 있어야 하고,
- 필요 시 `GET /api/v1/receipts/{receiptId}/status`로 **원본 OCR(ocr_raw)** 포함 전체 데이터를 조회하는 구조를 권장합니다.

### 5-2. 상태 단계(statusStage) 활용

- `AUTO_PROCESSING`: OCR/자동검증 중 (빠른 폴링)
- `MANUAL_REVIEW`: 관리자 검토 대기 (느린 폴링/대기 화면)
- `DONE`: 종결

관리자 웹에서는 `MANUAL_REVIEW` 상태의 건을 “검토 대기함”으로 쉽게 모아볼 수 있게 필터 기능을 권장합니다.

---

## 6. 관리자 웹 연동 “최소 구현 순서”

1) 판정 규칙 설정 화면 (`/api/v1/admin/rules/judgment`)  
2) 후보 상점 리스트 + 승인 (`/api/v1/admin/stores/candidates`, approve)  
3) 증거(영수증) 확인 기능(이미지 접근 방식 결정)  
4) submission 검색/조회(신규 API 추가)  
5) override + 콜백 재전송(신규 API 추가) + 감사로그

---

*문서 버전: 1.1 | 관리자 웹 연동 가이드*

