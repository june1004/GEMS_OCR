# 관리자 대시보드 BE 반영 요약

관리자 대시보드 구성 시 FE 요청사항에 따른 백엔드 반영 내용입니다.

---

## 1. 로그인 API – 조직 정보

- **POST /api/v1/auth/login**  
  - `user` 객체에 이미 포함: `organization_id` / `organizationId`, `org_name` / `orgName`, `org_type` / `orgType`, `campaignIds`  
  - 상세: [로그인_API_조직정보_요청사항.md](./로그인_API_조직정보_요청사항.md) 또는 `관리자_로그인_기관_권한_FE_지침.md`

---

## 2. 제출(Submissions) API – 422 대응 및 확장

### 2.0 쿼리 파라미터 (FE와 동일 이름 지원)

**GET /api/v1/admin/submissions** 에서 아래 파라미터를 지원합니다.

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `from` | string | 기간 시작 (YYYY-MM-DD). FE 권장 |
| `to` | string | 기간 끝 (YYYY-MM-DD) |
| `dateFrom` | string | 기간 시작 (위와 동일, 호환용) |
| `dateTo` | string | 기간 끝 (위와 동일, 호환용) |
| `campaignId` | int | 캠페인 ID로 필터 |
| `status` | string | MANUAL_REVIEW, FIT, UNFIT 등. **APPROVED** 는 BE에서 **FIT** 로 매핑 |
| `limit` | int | 1~2000 (기본 50, 대시보드 집계 시 1000 등 사용 가능) |
| `offset` | int | 페이징 |

- **응답**: `{ total: number, items: AdminSubmissionSummary[] }`  
- **items[]** 각 항목: `receiptId`, `userUuid`, **project_type**, **projectType** (STAY/TOUR, 대시보드 유형별 비중 차트용), `status`, `total_amount`, `created_at`

---

## 3. 대시보드 전용 집계 API

**GET /api/v1/admin/dashboard/stats**

- **쿼리**: `campaignId`, `from`, `to` (선택)
- **응답 예시**:
  - `todayCount`, `yesterdayCount`: 금일/전일 제출 건수
  - `pendingCount`: MANUAL_REVIEW 건수
  - `approvedAmountSum`: 승인(FIT) 건의 total_amount 합계
  - `byCategory`: `{ "STAY": n, "TOUR": m }` 유형별 건수
  - `dailyCounts`: `[{ "date": "YYYY-MM-DD", "count": n }, ...]` 일자별 추이

---

## 4. 반려 사유 집계 API

- **GET /api/v1/admin/dashboard/reject-reasons**  
- **GET /api/v1/admin/receipts/reject-reasons** (동일 응답, FE 문서 경로용)

- **쿼리**: `campaignId`, `from`, `to`, `limit` (기본 10, 최대 50)
- **응답**: `[{ "reason": "이미지 흐림", "count": 32 }, ...]`  
  - fail_reason / global_fail_reason 기준 집계, 반려(UNFIT 등) 건만 대상

---

## 5. Admin Context

- **GET /api/v1/admin/context**: 선택 캠페인(projectId 등) 저장값 조회  
- **PUT /api/v1/admin/context**: 선택 캠페인 등 저장  

기존 구현 유지.

---

## 6. 캠페인 API

- **GET /api/v1/admin/campaigns**, **GET /api/v1/admin/campaigns/:id**  
  - 응답에 **startDate**, **endDate**, **budget** (컬럼 존재 시) 포함.  
  - campaignId 기준 제출/집계 API와 연동되며, 기관·검수자는 할당된 캠페인만 조회 가능.

---

## 7. 영수증 이미지

- **GET /api/v1/admin/receipts/:receiptId/images**  
  - Presigned URL로 단기간 노출 (서버 설정 `PRESIGNED_URL_EXPIRES_SEC` 반영). 보안 스토리지 가이드라인 대응.

---

## 체크리스트 (BE 반영 완료)

| 항목 | 상태 |
|------|------|
| 로그인 응답 organization_id, org_name, org_type, campaignIds | ✅ |
| GET /admin/submissions 에 from, to, campaignId, status 지원 | ✅ |
| 제출 항목에 project_type, projectType 포함 | ✅ |
| 대시보드 전용 집계 API GET /admin/dashboard/stats | ✅ |
| 반려 사유 집계 API (dashboard/reject-reasons, receipts/reject-reasons) | ✅ |
| 캠페인 start_date/end_date/budget 노출 | ✅ |
| 영수증 이미지 Presigned URL | ✅ |
