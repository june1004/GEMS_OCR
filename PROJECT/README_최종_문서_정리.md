# 영수증 OCR 프로젝트 — 최종 문서 정리

> 현재까지 논의·결정 사항을 기준으로 한 문서·API·코드 정리 요약.  
> FE 개발사와 BE 개발사가 분리된 환경을 전제로 함.

---

## 1. 문서 구성 (최종)

| 문서 | 용도 | 전달 대상 |
|------|------|------------|
| **FE_API_규격_문서_외부전달용.md** | FE 연동에 필요한 API 규격만 정의 | **FE 개발사** (이 문서만 전달) |
| **FE_API_규격_문서.md** | FE + 관리자 API 전체 규격 (내부용) | BE/운영 |
| **README_최종_문서_정리.md** | 본 문서. 최종 정리·문서 목록·코드 반영 요약 | 내부 |

**FE 개발사 전달 범위**: 1 Presigned URL, 2 이미지 업로드, 3 Complete, 4 Status, 8 에러, 9 API 목록.  
**관리자 API(5·6·7번)** 는 보안상 FE 개발사에 전달하지 않음.

---

## 2. API 최종 사양 요약

### 2.1 FE 연동 (외부 전달)

- **1. Presigned URL**: `POST /api/v1/receipts/presigned-url` — uploadUrl, receiptId, objectKey 발급.
- **2. 이미지 업로드**: `PUT` (presigned uploadUrl) — 이미지 바이너리.
- **3. Complete**: `POST /api/v1/receipts/complete`  
  - Body: `receiptId`, `userUuid`, `type`, `documents[]`, **optional `data`**.  
  - **방식 2 (여러 폼데이터)**: `data` 사용 시 `data.items[]` 배열. `documents[i]`와 `data.items[i]` 1:1 대응, 동일 순서.  
  - `data.items[]` 요소: `amount`, `payDate`, `storeName`(선택), `location`(선택), `cardPrefix`(선택).
- **4. Status**: `GET /api/v1/receipts/{receiptId}/status` — 최종 판정·장별 items (OCR 결과, image_url 등).
- **8. 에러**: 4xx/5xx 시 `{ "detail": "메시지" }`, 409 등.
- **9. API 목록**: 위 4개 API만 외부 문서에 기재.

### 2.2 관리자 (내부·BE 전용, FE 개발사 비전달)

- 관리자 신청 단건 상세, 이미지 URL 발급, 수동 판정(override) 등은 **FE_API_규격_문서.md** 에만 포함.

---

## 3. 검수 유무별 연동 방식

| 구분 | 연동 방식 | Complete 요청 | 비고 |
|------|-----------|----------------|------|
| **검수 없는 경우** | documents-only | `documents` 만 전송, `data` 생략 | v1 권장. OCR만으로 자동 판정. |
| **검수 있는 경우** | documents + data | `documents` + `data.items[]` (장별 사용자 입력) | OCR 우선 비교, 불일치 시 PENDING_VERIFICATION → 관리자 검수. |

- **여러 폼데이터(방식 2)**: 영수증 여러 장일 때 **장별** 사용자 입력을 `data.items[]`로 전달. `documents`와 같은 길이·순서 유지.

---

## 4. 코드 반영 사항 (최종)

- **Complete 요청**: optional `data` 수신. `data` 사용 시 **`data.items[]`** (방식 2) 구조 지원.
- **저장**: Complete 시 `data`가 있으면 `submissions.user_input_snapshot`(JSONB)에 저장. 관리자 상세 조회 시 응답에 포함.
- **판정 로직**: `data.items[]`가 있으면 장별 인덱스로 사용자 입력과 OCR 비교(OCR 우선). 금액 10% 이상 불일치 시 PENDING_VERIFICATION.
- **기존 레거시**: `complete-legacy`는 기존 `StayData`/`TourData` 단일 객체 유지. 신규 FE는 메인 Complete + `data.items[]` 사용.
- **DB 마이그레이션**: `PROJECT/migrations/submissions_user_input_snapshot.sql` 적용 필요 (`user_input_snapshot` 컬럼 추가).

---

## 5. 참조 문서 목록

- FE 개발사 전달: `FE_API_규격_문서_외부전달용.md`
- 내부 전체 API: `FE_API_규격_문서.md`
- 개발 가이드: `FE_FASTAPI_DEVELOPER_GUIDE.md`, `FE_FASTAPI_API_SPEC.md`
- 검수·폼데이터 설명: `검수_유무_별_프로세스_및_API_정리.md`, `검수있는구조_API_변경사항_및_FE입력_OCR비교.md`, `FE_폼데이터_요청_응답_및_여러폼데이터_적용_설명.md`
