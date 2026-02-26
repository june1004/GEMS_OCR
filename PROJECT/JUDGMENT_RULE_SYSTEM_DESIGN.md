# 판정 규칙 운영 설계 (관리자 연동용)

> 목표: `판정 → DB 저장 → 콜백` 흐름에서 **판정 규칙을 하드코딩이 아닌 운영 정책으로 관리**할 수 있도록 구조화.

---

## 1) 핵심 컨셉

- 기존: 코드에 고정된 정책(예: 미등록 상점 처리, 최소 금액)
- 개선: DB의 `judgment_rule_config`를 기준으로 판정 분기
- 운영자(관리자 웹)에서 API로 정책 수정 가능

즉, **규칙을 “코드”가 아닌 “설정 데이터”로 분리**해 운영 탄력성을 확보합니다.

---

## 2) 이번 반영 범위

### 2-1. 규칙 설정 테이블

- Migration: `PROJECT/migrations/judgment_rule_config.sql`
- 테이블: `judgment_rule_config` (싱글톤 row: `id=1`)

주요 필드:
- `unknown_store_policy`: `AUTO_REGISTER | PENDING_NEW`
- `auto_register_threshold`: 자동 등록 임계치 (0.0~1.0)
- `enable_gemini_classifier`: 신규 상점 분류 시 Gemini 사용 여부
- `min_amount_stay`: STAY 최소 금액
- `min_amount_tour`: TOUR 최소 금액

### 2-2. 관리자 API

- `GET /api/v1/admin/rules/judgment`  
  현재 판정 정책 조회
- `PUT /api/v1/admin/rules/judgment`  
  판정 정책 수정

관리자 웹(`gems_ocr-9f4d37f5`)에서 이 API를 직접 호출하면 운영 중 규칙 변경이 가능합니다.

### 2-3. 분석 로직 연동

`analyze_receipt_task` 시작 시 정책 로드:
- `_get_judgment_rule_config(db)`

이후 판정에 사용:
- 미등록 상점 처리 정책(`unknown_store_policy`)
  - `PENDING_NEW`: 항상 대기 처리
  - `AUTO_REGISTER`: 분류 결과가 임계치 이상이면 자동 마스터 편입 후 재매칭
- 자동 편입 임계치(`auto_register_threshold`)
- Gemini 사용 여부(`enable_gemini_classifier`)
- 최소 금액(`min_amount_stay`, `min_amount_tour`)

---

## 3) 미등록 상점 처리 정책 (요청하신 예시)

### 정책 A: `PENDING_NEW`
- 마스터 미등록 상점 발견 시
  - `unregistered_stores`에 후보 저장
  - `PENDING_NEW`로 관리자 승인 전 대기
- 장점: 보수적 운영, 오등록 위험 최소화

### 정책 B: `AUTO_REGISTER`
- 마스터 미등록 상점 발견 시
  - 분류기 결과(`predicted_category`, `confidence`)가 임계치 이상이면
  - `master_stores` 자동 INSERT + `AUTO_REGISTERED`로 후보 이력 저장
  - 같은 요청 내 재매칭해 FIT 가능
- 장점: 자동화율 상승, 운영 개입 최소화

---

## 4) 관리자 웹 연동 포인트

관리자 웹에서 아래 화면/기능을 붙이면 운영 시스템이 완성됩니다.

1. **규칙 설정 화면**
   - unknown_store_policy 토글 (`PENDING_NEW` / `AUTO_REGISTER`)
   - auto_register_threshold 슬라이더
   - enable_gemini_classifier ON/OFF
   - min_amount_stay / min_amount_tour 입력

2. **신규 상점 후보 관리 화면**
   - 기존 API: `GET /api/v1/admin/stores/candidates`
   - 승인 API: `POST /api/v1/admin/stores/candidates/approve`

3. **운영 이력/감사**
   - 정책 변경 시 변경자/시간/변경 전후 값 로깅(차기 과제)

---

## 5) 차기 확장 권장

1. 지자체/캠페인별 세분 정책
   - `judgment_rule_config`를 캠페인/지역 단위로 확장
2. 키워드 관리 테이블화
   - 금지/허용 키워드(업종 분류)도 관리자 화면에서 CRUD
3. 정책 버저닝
   - submission별 적용된 규칙 버전 저장
4. 정책 변경 감사로그
   - 관리자 계정, 변경 시각, 필드 diff 보관

---

## 6) 기대 효과

- 정책 변경 시 코드 배포 없이 운영 대응 가능
- 관리자 승인 중심 운영과 자동화 중심 운영을 상황별로 전환 가능
- `판정 기준`이 데이터로 명시되어 FE/관리자/개발 간 커뮤니케이션 비용 절감

