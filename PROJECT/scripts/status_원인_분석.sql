-- status 별 문제·원인 분석 (DBeaver/psql에서 실행)
-- DB: gems

-- 1. 신청(submissions) status 별 건수
SELECT status, COUNT(*) AS cnt,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM submissions
GROUP BY status
ORDER BY cnt DESC;

-- 2. 신청 status 별 · project_type 별 건수
SELECT status, project_type, COUNT(*) AS cnt
FROM submissions
GROUP BY status, project_type
ORDER BY status, project_type;

-- 3. UNFIT/ERROR/PENDING 계열 신청의 fail_reason(원인) 별 건수
SELECT COALESCE(global_fail_reason, fail_reason, '(비어있음)') AS reason, COUNT(*) AS cnt
FROM submissions
WHERE status IN ('UNFIT', 'ERROR', 'PENDING', 'PENDING_NEW', 'PENDING_VERIFICATION', 'PROCESSING', 'VERIFYING')
GROUP BY COALESCE(global_fail_reason, fail_reason, '(비어있음)')
ORDER BY cnt DESC;

-- 4. 장(receipt_items) error_code 별 건수 (비적격/오류/대기 신청에 속한 장만)
SELECT ri.error_code, COUNT(*) AS cnt
FROM receipt_items ri
JOIN submissions s ON s.submission_id = ri.submission_id
WHERE s.status IN ('UNFIT', 'ERROR', 'PENDING', 'PENDING_NEW', 'PENDING_VERIFICATION')
GROUP BY ri.error_code
ORDER BY cnt DESC;

-- 5. 장(receipt_items) status 별 건수
SELECT status, COUNT(*) AS cnt
FROM receipt_items
GROUP BY status
ORDER BY cnt DESC;

-- 6. 최근 비적격/오류/대기 신청 샘플 (원인·audit 확인용)
SELECT submission_id, status, project_type,
       COALESCE(global_fail_reason, fail_reason) AS fail_reason,
       LEFT(audit_trail, 120) AS audit_trail,
       created_at
FROM submissions
WHERE status IN ('UNFIT', 'ERROR', 'PENDING_NEW', 'PENDING_VERIFICATION')
ORDER BY created_at DESC
LIMIT 30;

-- 8. OCR 미인식(ERROR_OCR / OCR_001) 건수·샘플 — 검증용
SELECT ri.error_code, COUNT(*) AS cnt
FROM receipt_items ri
WHERE ri.error_code = 'OCR_001'
GROUP BY ri.error_code;
-- OCR 미인식 장의 submission_id·image_key 샘플 (MinIO 객체 진단 스크립트 입력용)
SELECT ri.submission_id, ri.image_key, ri.error_code, ri.created_at
FROM receipt_items ri
WHERE ri.error_code = 'OCR_001'
ORDER BY ri.created_at DESC
LIMIT 50;

-- 7. 에러코드별 의미 (참고)
-- BIZ_001: 중복 등록  BIZ_002: 2026년 결제일 아님  BIZ_003: 최소 금액 미달
-- BIZ_004: 강원 외 지역  BIZ_005: 캠페인 기간 아님  BIZ_007: 입력금액-OCR 불일치
-- BIZ_008: 제외 업종  BIZ_010: 문서 구성 요건 불충족  BIZ_011: 영수증-OTA 금액 불일치
-- OCR_001: 영수증 판독 불가  PENDING_NEW: 신규 상점 검수 대기  PENDING_VERIFICATION: 수동 검증 대기
