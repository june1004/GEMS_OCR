# GEMS_OCR DB 주요 테이블·컬럼 설명

PostgreSQL 기준, `main.py`의 SQLAlchemy 모델 및 마이그레이션을 반영한 요약입니다.

---

## 1. submissions (제출·영수증 신청)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| **submission_id** | String (PK) | 제출(영수증) 고유 ID. receiptId로 FE/API 노출 |
| **user_uuid** | String | 사용자(시민) 식별자 |
| **project_type** | String | STAY(숙박) / TOUR(일반소비) |
| **campaign_id** | Integer | 캠페인 ID (기본 1) |
| **status** | String | PENDING \| PROCESSING \| VERIFYING \| FIT \| UNFIT \| ERROR \| PENDING_NEW \| PENDING_VERIFICATION 등 |
| **total_amount** | Integer | 적격 금액 합계(원). FIT 건 기준 |
| **global_fail_reason** | String | 전체 부적격/오류 사유 (255자 제한 권장) |
| **fail_reason** | String | 부적격 사유 (255자 제한 권장) |
| **audit_trail** | String | 감사·추적 로그(override 등) |
| **audit_log** | String | 판정 요약 로그 |
| **user_input_snapshot** | JSONB | Complete 시 FE가 보낸 data (items 등) |
| **submission_sidecar** | JSONB | (migration 적용 시) 교정 이력·Sidecar JSON §10 |
| **presigned_issued_count** | Integer | Presigned URL 발급 횟수 (TOUR 3매·STAY 2매 제한용) |
| **created_at** | DateTime | 생성 시각 |
| **updated_at** | DateTime | 수정 시각 (VERIFYING 타임아웃 판단용) |

---

## 2. receipt_items (영수증 장별)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| **item_id** | String (PK) | 장별 고유 ID |
| **submission_id** | String (FK) | 소속 제출 ID |
| **seq_no** | Integer | 업로드 순번 (1부터) |
| **doc_type** | String | RECEIPT 등 |
| **image_key** | String(500) | MinIO/S3 객체 키 |
| **store_name** | String | OCR 상점명 |
| **biz_num** | String | 사업자번호 |
| **pay_date** | String | 결제일 |
| **amount** | Integer | 금액 |
| **address** | String | 주소 (행정구역 집계·지역 매칭에 사용) |
| **location** | String | 시군구 등 위치 |
| **card_num** | String | 카드 번호 앞자리 (0000=미확정) |
| **status** | String | PENDING \| FIT \| UNFIT \| ERROR |
| **error_code** | String | BIZ_003, OCR_004 등 |
| **error_message** | String | 오류 메시지 |
| **confidence_score** | Integer | OCR 신뢰도 0~100 |
| **ocr_raw** | JSONB | OCR 원본 응답 |
| **parsed** | JSONB | 파싱 결과 |
| **created_at** | DateTime | 생성 시각 |

---

## 3. unregistered_stores (미등록 상점 후보)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| **id** | String (PK) | 후보 고유 ID |
| **store_name** | String(255) | 상점명 |
| **biz_num** | String(64) | 사업자번호 (Unique 제약에 참여) |
| **address** | String(500) | 주소 |
| **tel** | String(64) | 전화번호 |
| **status** | String(32) | TEMP_VALID \| PENDING_REVIEW \| APPROVED \| REJECTED |
| **source_submission_id** | String | 최초 검출된 submission_id |
| **occurrence_count** | Integer | 동일 상점 영수증 접수 횟수 |
| **first_detected_at** | DateTime | 최초 검출 시각 |
| **recent_receipt_id** | String(64) | 증거 확인용 최근 submission_id |
| **predicted_category** | String(64) | OCR/분류 예측 업종 |
| **category_confidence** | Float | 자동 분류 신뢰도 0.0~1.0 |
| **classifier_type** | String(20) | RULE \| SEMANTIC \| AI |
| **created_at**, **updated_at** | DateTime | |

- Unique 제약: `uq_unregistered_stores_biz_addr_tel` (biz_num, address, tel 조합 등). 중복 insert 시 UniqueViolation 발생 가능.

---

## 4. judgment_rule_config (판정 규칙·전역 설정)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| **id** | Integer (PK) | 1 고정 (단일 행) |
| **unknown_store_policy** | String(32) | AUTO_REGISTER \| PENDING_NEW (신규 상점 정책) |
| **auto_register_threshold** | Float | 자동 편입 신뢰도 임계 0.0~1.0 (기본 0.90) |
| **enable_gemini_classifier** | Boolean | Gemini 업종 분류 사용 여부 |
| **min_amount_stay** | Integer | STAY 최소 금액(원, 기본 60000) |
| **min_amount_tour** | Integer | TOUR 최소 금액(원, 기본 50000) |
| **orphan_object_minutes** | Integer | MinIO 고아 객체 유효기간(분) |
| **expired_candidate_minutes** | Integer | 만료 후보 유효기간(분) |
| **verifying_timeout_minutes** | Integer | VERIFYING 대기 허용(분). 0=비활성 |
| **verifying_timeout_action** | String(16) | UNFIT \| ERROR (타임아웃 시 적용) |
| **updated_at** | DateTime | |

---

## 5. admin_audit_log (관리자 감사 로그)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| **id** | BigInteger (PK) | 자동 증가 |
| **actor** | String(128) | 실행자(이메일 등) |
| **action** | String(64) | RULE_UPDATE \| SUBMISSION_OVERRIDE \| CALLBACK_SEND \| CALLBACK_RESEND \| EVIDENCE_VIEW 등 |
| **target_type** | String(64) | judgment_rule_config \| submission \| unregistered_store 등 |
| **target_id** | String(128) | 대상 ID |
| **before_json** | JSONB | 변경 전 스냅샷 |
| **after_json** | JSONB | 변경 후 스냅샷 |
| **meta** | JSONB | 부가 정보 (IP, purpose 등) |
| **created_at** | DateTime | |

---

## 6. organizations (기관·지자체)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| **id** | Integer (PK) | 기관 ID |
| **name** | String(255) | 기관명 |
| **sido_code** | String(8) | 행정 시도 코드 (예: 42) |
| **sigungu_code** | String(16) | 시군구 코드 |
| **created_at** | DateTime | |

---

## 7. admin_users (관리자·담당자)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| **id** | Integer (PK) | 사용자 ID |
| **email** | String(255) | 로그인 ID(이메일), unique |
| **password_hash** | String(255) | 비밀번호 해시 |
| **role** | String(32) | SUPER_ADMIN \| ORG_ADMIN \| CAMPAIGN_ADMIN |
| **organization_id** | Integer (FK) | 소속 기관 ID |
| **name** | String(255) | 담당자명 |
| **org_name** | String(255) | 소속명(캐시) |
| **is_active** | Boolean | 활성 여부 |
| **created_at**, **updated_at** | DateTime | |

---

## 8. admin_campaign_access (담당자–캠페인 권한)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| **admin_user_id** | Integer (PK, FK) | admin_users.id |
| **campaign_id** | Integer (PK) | 접근 가능 캠페인 ID |
| **created_at** | DateTime | |

- SUPER_ADMIN은 이 테이블 없이 전체 캠페인 접근.

---

## 9. pending_signups (가입 대기)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| **id** | Integer (PK) | |
| **email** | String(255) | 가입 이메일 |
| **password_hash** | String(255) | |
| **name** | String(255) | 이름 |
| **phone** | String(64) | 전화 |
| **org_type** | String(32) | 기관 유형 |
| **sido_code**, **sido_name** | String | 시도 코드/명 |
| **sigungu_code**, **sigungu_name** | String | 시군구 코드/명 |
| **org_name**, **department** | String | 기관명, 부서 |
| **status** | String(16) | pending \| approved \| rejected |
| **created_at**, **updated_at** | DateTime | |

---

## 10. campaigns (캠페인)

- ORM 없이 raw SQL로 조회/삽입/수정. 마이그레이션으로 생성·확장.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| **campaign_id** | SERIAL (PK) | 캠페인 ID |
| **campaign_name** | VARCHAR(255) | 캠페인명 |
| **is_active** | BOOLEAN | 활성 여부 |
| **target_city_county** | VARCHAR(50) | 대상 시군구 (NULL=전체) |
| **start_date**, **end_date** | DATE | 캠페인 기간 |
| **budget** | BIGINT | (migration 적용 시) 예산. 대시보드 예산 소진률용 |
| **priority** | Integer | (확장 시) 정렬 우선순위 |
| **project_type** | String | (확장 시) STAY/TOUR |
| **created_at**, **updated_at** | TIMESTAMP | |

---

## 관계 요약

- **submissions** 1 : N **receipt_items** (submission_id)
- **submissions.campaign_id** → **campaigns.campaign_id**
- **admin_users.organization_id** → **organizations.id**
- **admin_campaign_access** → **admin_users**, **campaigns**
- **unregistered_stores**: 영수증 OCR 시 미등록 상점 후보로 적재; Unique 제약으로 (biz_num, address, tel) 중복 방지.
