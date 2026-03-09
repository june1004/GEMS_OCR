# 관리자 로그인·기관·캠페인 권한 — FE 연동 지침

> 슈퍼관리자·지자체 기관·담당자 회원가입·캠페인별 권한 및 **영수증 등 개인정보 보안** 반영 지침.  
> 관리자 페이지 FE는 아래 API·플로우에 맞춰 연동하면 됩니다.

---

## 1. 개요

- **로그인 ID**: 이메일
- **비밀번호 정책**: 영문 **대문자·소문자 각 1자 이상**, **숫자**, **특수문자** 포함, **최소 8자**
- **역할**: `SUPER_ADMIN`(전체) | `ORG_ADMIN` | `CAMPAIGN_ADMIN`(캠페인별만 조회)
- **캠페인 스코프**: 담당자는 **할당된 캠페인**에 해당하는 신청(영수증)만 조회·override 가능. 슈퍼관리자는 전체.

---

## 2. 인증 방식 (둘 다 지원)

| 방식 | 용도 | 헤더 |
|------|------|------|
| **Bearer JWT** | 담당자 로그인 후 API 호출 | `Authorization: Bearer <access_token>` |
| **X-Admin-Key** | 레거시·슈퍼(환경변수와 동일 시 전체 권한) | `X-Admin-Key: <ADMIN_API_KEY>` |

- JWT 사용 시: 로그인 API로 `access_token` 발급 후, 모든 관리자 API 요청에 `Authorization: Bearer <access_token>` 포함.
- X-Admin-Key 사용 시: 슈퍼관리자와 동일하게 전체 캠페인 접근(기존 동작).

---

## 3. API 목록

### 3.1 로그인·현재 사용자 (Admin - Auth)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/v1/auth/login` | 이메일·비밀번호 로그인 → JWT 및 사용자 정보 반환 |
| GET | `/api/v1/admin/me` | 현재 로그인 담당자 정보(캠페인 목록 포함). **인증 필수** |

**POST /api/v1/auth/login**

- Request body: `{ "email": "admin@example.com", "password": "Abc1!xyz" }`
- Response: `{ "access_token": "...", "token_type": "bearer", "user": { "id", "email", "role", "name", "organizationId", "org_name", "campaignIds" } }`
- `user.name`: 담당자 이름(없으면 FE에서 이메일 @ 앞부분 표시)
- `user.org_name`: 소속명(기관명). FE에서 "소속(기관정보)" 표시 시 `org_type`과 조합 가능
- `user.campaignIds`: 접근 가능 캠페인 ID 배열. 담당자는 이 ID만 캠페인 선택·검수 큐에서 사용
- 401: 이메일/비밀번호 오류 또는 비활성 계정

**GET /api/v1/admin/me**

- Header: `Authorization: Bearer <token>` 또는 `X-Admin-Key`
- Response: `{ "id", "email", "role", "name", "organizationId", "organizationName", "org_name", "campaignIds", "isSuper" }`
- 담당자: `campaignIds`에 접근 가능한 캠페인 ID 목록. FE는 `allowedCampaignIds`로 저장 후 캠페인/검수 큐 필터에 사용.
- 슈퍼: `isSuper: true`, `campaignIds` 빈 배열.

---

### 3.2 기관 (Admin - Organizations, 슈퍼관리자 전용)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/v1/admin/organizations` | 기관 생성(지자체 시도/시군구별) |
| GET | `/api/v1/admin/organizations` | 기관 목록 조회 |

- Request 생성: `{ "name": "강원도 춘천시", "sidoCode": "42", "sigunguCode": "42110" }`
- 403: 슈퍼관리자가 아닌 경우

---

### 3.3 담당자 (Admin - Users, 슈퍼관리자 전용)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/v1/admin/users` | 담당자 회원가입(이메일·비밀번호·역할·캠페인 권한) |
| GET | `/api/v1/admin/users` | 담당자 목록 |
| PUT | `/api/v1/admin/users/{user_id}/campaigns` | 해당 담당자의 접근 가능 캠페인 ID 목록 변경 |

**POST /api/v1/admin/users**

- Request: `{ "email", "password", "role": "CAMPAIGN_ADMIN", "organizationId": null, "campaignIds": [1, 2] }`
- 비밀번호: 위 비밀번호 정책 만족해야 400 없음.
- 409: 이메일 중복.

**GET /api/v1/admin/users** (담당자 목록, 슈퍼관리자 전용)

- Response: `AdminUserItem[]`. 각 항목: `id`, `email`, `role`, `organizationId`, `organization_name`, `name`, `org_name`, `org_type`, `isActive`, `campaignIds`, `createdAt`
- `name`: 담당자 이름. 없으면 FE에서 이메일 @ 앞부분으로 표시(displayName)
- `org_name` / `organization_name`: 소속(기관)명. FE에서 "소속(기관정보)" 컬럼에 `org_type`과 "지자체 · 강원특별자치도청" 형태로 표시(displayAffiliation)
- `org_type`: 기관 유형(지자체 등). DB에 컬럼 없으면 null
- `campaignIds`: 접근 캠페인 ID 배열. FE에서 배지로 표시, 매칭 없으면 "N건 (목록에 없음)"

**PUT /api/v1/admin/users/{user_id}/campaigns**

- Request: `{ "campaignIds": [1, 2, 3] }`  
- 해당 담당자는 이 ID들에 해당하는 캠페인만 신청(영수증) 조회 가능.

---

### 3.4 캠페인·신청(영수증) — 권한 스코프 적용

- **GET /api/v1/admin/campaigns**: 담당자는 **할당된 캠페인만** 목록에 노출. 슈퍼는 전체.
- **GET /api/v1/admin/submissions**: 담당자는 **해당 캠페인에 속한 신청만** 목록/검색.
- **GET /api/v1/admin/submissions/{receiptId}**: 해당 신청의 `campaign_id`가 담당자 `campaignIds`에 없으면 404.
- **GET /api/v1/admin/submissions/{receiptId}/images**: 위와 동일(영수증 이미지도 동일 스코프).
- **POST /api/v1/admin/submissions/{receiptId}/override**: 위와 동일(override도 동일 스코프).

FE에서는 로그인 후 `GET /api/v1/admin/me`로 `campaignIds`·`isSuper`를 받아, 목록/상세/override 호출 시 **백엔드가 이미 스코프를 적용**하므로 별도 필터링은 불필요. 단, **캠페인 선택 UI**는 `GET /api/v1/admin/campaigns` 결과만 보여 주면 됨(이미 스코프 적용됨).

---

## 4. FE 권장 플로우

1. **로그인 화면**  
   - 이메일·비밀번호 입력 → `POST /api/v1/auth/login`.  
   - 성공 시 `access_token`을 저장(예: 메모리·세션스토리지·쿠키)하고, 이후 모든 관리자 API에 `Authorization: Bearer <access_token>` 포함.

2. **초기 로드(메인/대시보드)**  
   - `GET /api/v1/admin/me`로 현재 사용자와 `campaignIds`·`isSuper` 획득.  
   - 슈퍼가 아니면 캠페인 필터/탭을 `campaignIds` 기준으로만 구성(선택 사항).

3. **신청(영수증) 목록**  
   - `GET /api/v1/admin/submissions?...` 호출.  
   - 백엔드가 캠페인 스코프를 적용하므로, 응답만 그대로 표시.

4. **신청 상세·이미지·override**  
   - `receiptId` 기준으로 상세/이미지/override API 호출.  
   - 권한 없으면 404로 내려오므로, FE는 404 시 "권한 없음" 또는 "없는 신청" 메시지 처리.

5. **슈퍼관리자 전용 메뉴**  
   - `GET /api/v1/admin/me`의 `isSuper === true`일 때만 **기관 관리**, **담당자 관리**(회원가입·캠페인 권한 설정) 메뉴 노출.

6. **비밀번호 입력(회원가입·비밀번호 변경)**  
   - 클라이언트에서 정규식으로 위 정책 검사 후 전송 권장.  
   - 정책: 영문 대·소문자 각 1자 이상, 숫자, 특수문자, 8자 이상.

---

## 5. 보안(개인정보) 관련

- 영수증·신청 데이터는 **캠페인 단위로만** 노출. 담당자는 할당된 캠페인에 해당하는 데이터만 조회·override 가능.
- 인증은 **JWT(Bearer)** 또는 **X-Admin-Key** 중 하나 필수. 미제공 시 401.
- 슈퍼관리자만 기관·담당자 생성·수정·캠페인 권한 변경 가능(403 처리).

---

## 6. 슈퍼관리자 최초 생성

- **방법 1**: 서버에 `ADMIN_API_KEY`가 설정된 상태에서 `POST /api/v1/admin/users`를 **X-Admin-Key**로 호출하여 `role: "SUPER_ADMIN"` 담당자 1명 생성.
- **방법 2**: 스크립트 실행  
  `SUPER_ADMIN_EMAIL=admin@example.com SUPER_ADMIN_PASSWORD='Abc1!xyz' python PROJECT/scripts/create_super_admin.py`  
  (DB 마이그레이션 `admin_organizations_and_users.sql` 적용 후, `admin_users` 테이블이 비어 있을 때 1회 실행.)

---

## 7. 환경 변수(서버)

| 변수 | 설명 |
|------|------|
| `JWT_SECRET` | JWT 서명용. 설정 시 로그인·Bearer 인증 사용. |
| `ADMIN_API_KEY` | X-Admin-Key와 일치 시 슈퍼관리자 권한. |
| `JWT_EXPIRE_MINUTES` | (선택) 토큰 유효 분. 기본 480(8시간). |

---

## 8. Swagger 문서

- **관리자 API**: `/admin-docs`  
- 로그인·기관·담당자·캠페인 스코프 적용 API는 **Admin - Auth**, **Admin - Organizations**, **Admin - Users**, **Admin - Campaigns**, **Admin - Submissions** 태그에서 확인.
