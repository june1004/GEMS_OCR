# 영수증 OCR 프로젝트 — 최종 문서 정리 (요약)

> **문서 역할 정리·중복 제거·읽는 순서** 는 **[문서_정리_통합.md](문서_정리_통합.md)** 에 통합되어 있습니다.  
> **관리자 페이지 추가 개발** 은 **[관리자_페이지_추가_개발_지침.md](관리자_페이지_추가_개발_지침.md)** 를 참고하세요.

---

## 1. 문서 진입점

| 목적 | 문서 |
|------|------|
| 문서 전체 정리·중복 제거·역할 정리 | [문서_정리_통합.md](문서_정리_통합.md) |
| 문서 읽는 순서만 빠르게 | [00_문서_읽는_순서.md](00_문서_읽는_순서.md) |
| FE 개발사 전달 | [FE_API_규격_문서_외부전달용.md](FE_API_규격_문서_외부전달용.md) |
| 관리자 추가 개발 | [관리자_페이지_추가_개발_지침.md](관리자_페이지_추가_개발_지침.md) |

---

## 2. API·코드 반영 요약

- **FE**: Presigned → 업로드(PUT) → Complete(documents, optional data.items[]) → Status(폴링/콜백).  
  관리자 API는 FE 개발사에 전달하지 않음.
- **Complete data**: `data.items[]` 지원. 있으면 `user_input_snapshot` 저장, 관리자 상세에 노출.
- **관리자**: 판정 규칙(유효일 `orphan_object_days`, `expired_candidate_days` 포함), 상세(user_input_snapshot), override, 콜백 재전송, 이미지 presigned.
- **마이그레이션**: `migrations/submissions_user_input_snapshot.sql`, `migrations/judgment_rule_config_minio_days.sql` 등.

---

## 3. 참조

- 상세 문서 목록·역할·중복 정리: **문서_정리_통합.md**
- 관리자 웹 연동 전반: **ADMIN_PORTAL_GUIDE.md**
