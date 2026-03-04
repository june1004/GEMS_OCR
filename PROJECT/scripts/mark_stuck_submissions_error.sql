-- 분석 중 멈춘 신청(PROCESSING/VERIFYING)을 ERROR로 복구
-- DB: gems
-- 사용: 특정 ID만 복구하거나, N분 이상 지난 건 일괄 복구

-- 1) 특정 submission_id 1건만 ERROR로 복구 (예: f6d101e4-749e-4847-88d6-f05e35e8fd5c)
/*
UPDATE submissions
SET status = 'ERROR',
    global_fail_reason = '분석 지연(수동 조치)',
    fail_reason = '분석 지연(수동 조치)',
    audit_trail = COALESCE(audit_trail, '') || ' | [복구] VERIFYING/PROCESSING 상태에서 수동으로 ERROR 처리',
    audit_log = COALESCE(audit_log, '') || ' | [복구] 수동 ERROR 처리'
WHERE submission_id = 'f6d101e4-749e-4847-88d6-f05e35e8fd5c'
  AND status IN ('PROCESSING', 'VERIFYING');
*/

-- 2) 15분 이상 PROCESSING/VERIFYING 상태인 건 일괄 ERROR 복구
/*
UPDATE submissions
SET status = 'ERROR',
    global_fail_reason = '분석 지연(자동 복구)',
    fail_reason = '분석 지연(자동 복구)',
    audit_trail = COALESCE(audit_trail, '') || ' | [복구] ' || NOW()::text || ' 자동 ERROR 처리',
    audit_log = COALESCE(audit_log, '') || ' | [복구] 자동 ERROR 처리'
WHERE status IN ('PROCESSING', 'VERIFYING')
  AND created_at < NOW() - INTERVAL '15 minutes';
*/

-- 3) 해당 ID 현재 상태 확인 (실행 후 확인용)
SELECT submission_id, status, project_type, fail_reason, global_fail_reason, created_at, audit_trail
FROM submissions
WHERE submission_id = 'f6d101e4-749e-4847-88d6-f05e35e8fd5c';
