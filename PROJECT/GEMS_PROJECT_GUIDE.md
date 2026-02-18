
# 2026 혜택받go 강원 여행 인센티브 지원사업 개발 가이드 (PRD & Tech Spec)

## 1. 프로젝트 목적 및 범위
본 프로젝트는 강원특별자치도 방문객의 소비 영수증을 OCR로 분석하여 인센티브(강원상품권)를 자동 지급하는 시스템입니다.

## 2. 핵심 비즈니스 로직 (Business Logic)
- **숙박 지원**: 60,000원 이상 결제 시 30,000원 지급 (1인당 최대 3매)
- **관광 소비**: 50,000원 이상 결제 시 10,000원 지급 (1인당 최대 3매)
- **제한**: 2026년 발행 영수증, 강원도 외 거주자 한정, 유흥주점 제외.

## 3. 백엔드(FastAPI) 개발 단계
### Phase 1: 인프라 연동
- [x] Coolify를 통한 PostgreSQL, MinIO 설치 및 도메인 연결
- [x] MinIO CORS 설정 (easy.gwd.go.kr 허용)

### Phase 2: API 엔드포인트 구현 (Missing Endpoints)
1. `POST /api/v1/receipts/presigned-url`: S3 업로드 URL 생성
2. `POST /api/v1/receipts/complete`:
   - S3 이미지 -> Naver OCR 호출
   - 결과값 DB 저장
   - CSV(음식점 현황) 비교 로직 수행
   - Gemini API를 이용한 업종 검증 (유흥주점 필터링)
3. `GET /api/v1/receipts/{receiptId}/status`: 결과 반환

================

`https://api.nanum.online/docs#/` (FastAPI Swagger UI) 페이지에 접속하여, 내부 설계안 및 API 테스트 가이드와 대조했을 때 확인 및 수정해야 할 주요 사항을 정리해 드립니다.

1. 엔드포인트 구성 및 경로 확인 

* 설계안에 명시된 핵심 3단계 플로우가 모두 포함되어 있는지 확인하세요:
* **`POST /api/v1/receipts/presigned-url`**: 업로드용 URL 발행 (Input: `fileName`, `contentType`) 

* **`POST /api/v1/receipts/complete`**: 업로드 완료 알림 및 OCR 트리거 (Input: `receiptId`, `objectKey`) 

* **`GET /api/v1/receipts/{receiptId}/status`**: 분석 결과 및 상태 조회 (Path Variable: `receiptId`) 



2. 응답 데이터 스키마 업데이트 (신규 필드 반영) 

* 최근 업데이트된 **데이터 자산화 전략**에 따라 `status` 조회 결과에 다음 필드들이 포함되어 있는지 점검이 필요합니다:

* **`address` (신규)**: 지역별 이용 현황 분석을 위한 가맹점 주소 


* **`cardPrefix` (신규)**: 결제 수단 분석을 위한 카드번호 앞 4자리 (비식별화 조치) 


* **`confidence`**: OCR 인식 신뢰도 점수 (제미나이 2차 검증 시 활용) 



3. 서버 주소(Base URL) 설정 확인 

* Swagger UI 상단의 **Servers** 목록에 `https://api.nanum.online`이 올바르게 등록되어 있는지 확인하세요.


* 일부 문서(Postman 가이드)에 언급된 `api.gangwon-benefit.kr` 대신, 현재 실제 주소인 `api.nanum.online`으로 통일되어야 프론트엔드 개발자가 혼동하지 않습니다.



4. 비즈니스 로직 및 에러 코드 명세 

* **상태 값 정의**: OCR 처리 중일 때의 `PENDING`, 성공 시 `SUCCESS`, 실패 시 `FAIL_UNIDENTIFIABLE`(영수증 식별 불가 등)과 같은 상태 값이 스키마 설명(Description)에 명시되어 있는지 확인하세요.


* **데이터 자산화 구조**: 내부 PostgreSQL에는 Raw 데이터(전체 JSON)를 저장하고, 외부 시스템에는 정제된 데이터(주소, 카드 앞 4자리 등)만 전송하는 구조가 반영되었는지 확인이 필요합니다.



5. 프론트엔드 연동 주의사항 

* **생성 시점**: `receiptId`와 `objectKey`가 1단계(`presigned-url`) 응답 시점에 백엔드에서 생성되어 반환되는지 확인하세요. 이는 전체 프로세스의 고유 식별자로 사용됩니다.


**수정 사항 요약:** Swagger UI에서 **`address`**와 **`cardPrefix`** 필드가 누락되었다면 모델(Schemas) 정의를 수정하시고, 각 엔드포인트의 **Example Value**가 위 규격과 일치하도록 업데이트하는 것을 추천합니다.

===========================











### Phase 3: 데이터 자산화 및 관리자 페이지
- PostgreSQL 데이터를 기반으로 지역별/업종별 KPI 추출
- React 기반 관리자 대시보드 구축

## 4. 환경 변수 설정 (.env)
```text
DATABASE_URL=postgresql://user:password@gems-db:5432/postgres
S3_ENDPOINT=https://storage-api.nanum.online
S3_ACCESS_KEY=gems_master
S3_SECRET_KEY=your_secret
S3_BUCKET=gems-receipts
NAVER_OCR_INVOKE_URL=your_naver_url
NAVER_OCR_SECRET=your_naver_secret
GEMINI_API_KEY=your_gemini_key
```

## 5. 보안 및 최적화
- 카드번호 앞 4자리 외 마스킹 처리
- CI 정보를 UUID로 매핑하여 개인정보 최소화
- OCR 신뢰도(Confidence) 0.8 미만일 경우 관리자 '수동 확인' 플래그 설정
