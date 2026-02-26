# PROJECT 문서 인덱스

중복 문서를 정리하고, 실제 운영 시 참고할 핵심 문서를 아래로 통합했습니다.

---

## 1) FE ↔ BE 연동 (기준 문서)

- `FE_FASTAPI_API_SPEC.md`  
  - FE 업로드/complete/status 전체 스펙
  - 장별 에러코드 표
  - 폴링 정책
  - **결과 콜백(BE→FE) 및 FE 스케줄러 복구 정책 포함**

> 기존 QA/요약 문서는 중복되어 제거하고, 위 문서로 통합했습니다.

---

## 2) 운영용 요약 (외부 공유용)

- `FE_API_SPEC_EXTERNAL.md`  
  - 외부 파트너 공유용 흐름 요약
- `FE_API_SPEC_ONE_PAGE.md`  
  - 실무 연동용 1페이지 요약 스펙

---

## 3) 판정 규칙/자동 분류 설계

- `JUDGMENT_RULE_SYSTEM_DESIGN.md`  
  - 판정 규칙 운영 구조(관리자 규칙 API 포함)
- `ADMIN_PORTAL_GUIDE.md`
  - 관리자 웹 연동 체크리스트/운영 보강 지침
- `GEMINI_CLASSIFIER_GUIDE.md`  
  - 업종 자동 분류의 Gemini 연동 가이드

---

## 4) 마이그레이션/운영 가이드

- `DBEAVER_MIGRATION_GUIDE.md`
- `migrations/*.sql`

