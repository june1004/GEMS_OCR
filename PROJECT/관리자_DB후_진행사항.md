# 관리자 기능 — DB 작업 후 진행 사항

> `organizations`, `admin_users`, `admin_campaign_access` 테이블 생성이 끝난 뒤 해야 할 일을 순서대로 정리했습니다.

---

## ✅ 체크리스트

| 순서 | 할 일 | 쿨리파이 | 로컬 |
|------|--------|----------|------|
| **1** | DB 마이그레이션 | ✅ DBeaver에서 완료 | ✅ DBeaver에서 완료 |
| **2** | 패키지 설치 | 저장소 반영 후 **재빌드·재배포** | 터미널: `pip install -r requirements.txt` |
| **3** | JWT 환경변수 | 앱 환경변수에 **JWT_SECRET** 추가 후 재시작 | `.env`에 `JWT_SECRET=...` 추가 후 서버 재시작 |
| **4** | 최초 슈퍼관리자 생성 | curl로 API 호출 (아래 예시) | curl 또는 스크립트 (아래 예시) |

---

## 2. 패키지 설치

- **쿨리파이**: 코드 푸시 후 **재빌드**하면 `requirements.txt`에 있는 PyJWT, passlib가 자동 설치됨. 별도 명령 없음.
- **로컬**: 프로젝트 폴더에서  
  `pip install -r requirements.txt`

---

## 3. JWT_SECRET 설정

- **쿨리파이**: 서비스 → Environment Variables → `JWT_SECRET` 추가 (값 32자 이상 권장) → 저장 후 **재시작**.
- **로컬**: `.env`에 한 줄 추가  
  `JWT_SECRET=아무거나_32자_이상_비밀문자열`  
  이후 uvicorn 등 서버 다시 실행.

---

## 4. 최초 슈퍼관리자 1명 만들기

**한 번만** 하면 됩니다.

### 쿨리파이 (실서버)

터미널(로컬이어도 됨)에서 아래 한 번 실행. `X-Admin-Key`와 이메일·비밀번호만 바꾸면 됨.

```bash
curl -X POST "https://api.nanum.online/api/v1/admin/users" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: 여기에_쿨리파이에_설정한_ADMIN_API_KEY" \
  -d '{"email":"super@example.com","password":"Abc1!xyz","role":"SUPER_ADMIN","campaignIds":[]}'
```

- 비밀번호: **영문 대·소문자 각 1자 이상 + 숫자 + 특수문자 + 8자 이상** (예: `Abc1!xyz`).

### 로컬

- **방법 A** — 위 curl에서 주소만 `http://localhost:8000`으로 바꾸고, `X-Admin-Key`는 로컬 `.env`의 `ADMIN_API_KEY`로 호출.
- **방법 B** — 스크립트:  
  `SUPER_ADMIN_EMAIL=admin@example.com SUPER_ADMIN_PASSWORD='Abc1!xyz' python PROJECT/scripts/create_super_admin.py`

---

## 5. 완료 확인

1. **로그인**  
   `POST /api/v1/auth/login`  
   body: `{"email":"super@example.com","password":"Abc1!xyz"}`  
   → `access_token` 이 오면 성공.

2. **현재 사용자**  
   `GET /api/v1/admin/me`  
   Header: `Authorization: Bearer 위에서_받은_access_token`  
   → `isSuper: true`, `role: "SUPER_ADMIN"` 이면 정상.

3. **관리자 문서**  
   브라우저에서 `https://api.nanum.online/admin-docs` (또는 로컬 주소) 열어서 Admin - Auth / Admin - Users 등이 보이면 적용된 상태.

---

## 요약 한 줄

**DB 완료 → (재빌드/패키지 설치) → JWT_SECRET 설정 → X-Admin-Key로 슈퍼관리자 1명 API 생성 → 로그인 테스트.**
