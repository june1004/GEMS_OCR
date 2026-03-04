# PROJECT/scripts — DB 분석·유틸

## status 별 원인 분석 (FIT 적고 UNFIT/ERROR/PENDING 많을 때)

### 방법 1: Python 스크립트 (권장)

프로젝트 루트에서:

```bash
# .env 에 DATABASE_URL 설정 후
python PROJECT/scripts/analyze_status_causes.py
```

**출력 내용**

1. 신청(submissions) **status 별 건수** (비율)
2. status 별 · **project_type(STAY/TOUR)** 별 건수
3. UNFIT/ERROR/PENDING 계열의 **fail_reason(원인)** 별 건수
4. 비적격/오류/대기 신청에 속한 **장(receipt_items)의 error_code** 별 건수
5. **장 status** 별 건수
6. 최근 비적격/오류/대기 신청 **샘플 20건** (원인·시각 확인)

3·4번에서 상위 원인과 에러코드를 확인한 뒤, 규칙 완화·OCR 개선·FE 안내 등을 검토하면 됩니다.

### 방법 2: SQL 직접 실행

DBeaver·psql 등에서 `PROJECT/scripts/status_원인_분석.sql` 을 열고 쿼리 블록 단위로 실행합니다.

- 1~2: status·project_type 별 건수
- 3: fail_reason 별 건수 (원인 파악)
- 4~5: receipt_items error_code·status 별 건수
- 6: 최근 비적격/오류/대기 신청 샘플 (audit_trail 포함)
- 7: 에러코드 의미 참고 주석

### 에러코드 참고 (FE_FASTAPI_API_SPEC.md)

| error_code | 의미 |
|------------|------|
| BIZ_001 | 중복 등록 |
| BIZ_002 | 2026년 결제일 아님 |
| BIZ_003 | 최소 금액 미달 (TOUR 5만/STAY 6만) |
| BIZ_004 | 강원 외 지역 |
| BIZ_007 | 입력 금액–OCR 불일치 |
| BIZ_008 | 제외 업종 |
| BIZ_010 | 문서 구성 요건 불충족 |
| BIZ_011 | 영수증–OTA 금액 불일치 |
| OCR_001 | 영수증 판독 불가 |
| PENDING_NEW | 신규 상점 검수 대기 |
| PENDING_VERIFICATION | 수동 검증 대기 |

---

## 분석 중 멈춘 신청(PROCESSING/VERIFYING) 복구

OCR 분석 태스크가 중단되거나 타임아웃 등으로 submission이 **PROCESSING** 또는 **VERIFYING** 상태에 오래 머무를 때, ERROR로 수동/일괄 복구할 수 있습니다.

### 방법 1: Python 스크립트

```bash
# 특정 ID 1건만 ERROR로 복구
python PROJECT/scripts/mark_stuck_submissions_error.py f6d101e4-749e-4847-88d6-f05e35e8fd5c

# 15분 이상 지난 PROCESSING/VERIFYING 건 일괄 복구 (기본 15분)
python PROJECT/scripts/mark_stuck_submissions_error.py --all

# N분 이상 지난 건만 일괄 복구
python PROJECT/scripts/mark_stuck_submissions_error.py --all --minutes 30
```

### 방법 2: SQL 직접 실행

`PROJECT/scripts/mark_stuck_submissions_error.sql` 을 열어서:

- **1)** 특정 `submission_id` 1건만 복구: 해당 블록의 주석을 해제하고 ID를 넣은 뒤 실행
- **2)** 15분 이상 지난 건 일괄 복구: 해당 블록 주석 해제 후 실행
- **3)** 복구 후 상태 확인: `SELECT` 쿼리로 해당 ID 조회

---

## MinIO에 저장됐는데 이미지가 안 보일 때

MinIO에는 객체가 있는데 브라우저/뷰어에서 이미지가 안 나오는 경우, **Presigned PUT 시 본문이 실제 이미지 바이너리가 아닐 수 있음** (JSON/FormData로 전송된 경우).

### 1) 객체 진단 스크립트

`.env`에 S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET 설정 후 (또는 GitHub Actions에서는 Repository Secrets 사용):

```bash
# objectKey는 presigned 응답의 objectKey 그대로 (receipts/ 접두어 있음)
python PROJECT/scripts/check_s3_image_object.py receipts/08fc5d49-115e-4bed-9a2d-cdae128d0c54_33a3cf08_receipt-test.png

# receipts/ 없이 파일명만 넣어도 스크립트가 receipts/ 를 붙여서 조회
python PROJECT/scripts/check_s3_image_object.py 08fc5d49-115e-4bed-9a2d-cdae128d0c54_33a3cf08_receipt-test.png
```

- **PNG/JPEG 시그니처 일치** → 저장된 내용은 이미지. 뷰어/Content-Type 문제일 수 있음.
- **JSON으로 보임** → FE가 Presigned URL로 PUT 할 때 `body`를 **파일 바이너리**가 아니라 JSON 등으로 보낸 것.
- **multipart로 보임** → FormData 전체를 body로 보낸 것.

### 2) FE 업로드 요건 (해결)

Presigned URL로 **PUT** 할 때 반드시:

- **body**: 이미지 파일의 **원시 바이너리**만 전송 (예: `fetch(uploadUrl, { method: "PUT", body: file })`).
- **Content-Type**: Presigned URL 발급 시 사용한 `contentType`과 **동일**하게 전송 (예: `image/png`, `image/jpeg`).
- **하지 말 것**: `body: JSON.stringify(...)`, `FormData`를 body로 전송, base64 문자열만 보내기.

### 3) Git push 시 자동 실행

`main`/`master` 브랜치에 push하면 `.github/workflows/check-s3-image.yml`이 실행되어 `check_s3_image_object.py`가 동작합니다.  
Repository Secrets에 `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, (선택) `S3_BUCKET`, `S3_CHECK_OBJECT_KEY`(검사할 객체 키)를 넣어 두면 해당 객체에 대해 진단이 수행됩니다. `S3_CHECK_OBJECT_KEY`를 비워 두면 스크립트만 실행되고(인자 없음) 단계는 성공 처리됩니다.
