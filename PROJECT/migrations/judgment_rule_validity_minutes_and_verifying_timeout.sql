-- 유효기간을 분 단위로 설정 가능 + VERIFYING 대기 시간 초과 정책
-- 적용 DB: gems

-- 1) judgment_rule_config: 분 단위 컬럼 추가 (일 단위와 병행, 분 우선 사용)
ALTER TABLE judgment_rule_config
ADD COLUMN IF NOT EXISTS orphan_object_minutes INTEGER;

ALTER TABLE judgment_rule_config
ADD COLUMN IF NOT EXISTS expired_candidate_minutes INTEGER;

UPDATE judgment_rule_config
SET orphan_object_minutes = COALESCE(orphan_object_days, 1) * 1440
WHERE id = 1 AND orphan_object_minutes IS NULL;

UPDATE judgment_rule_config
SET expired_candidate_minutes = COALESCE(expired_candidate_days, 1) * 1440
WHERE id = 1 AND expired_candidate_minutes IS NULL;

ALTER TABLE judgment_rule_config
ALTER COLUMN orphan_object_minutes SET DEFAULT 1440;

ALTER TABLE judgment_rule_config
ALTER COLUMN expired_candidate_minutes SET DEFAULT 1440;

COMMENT ON COLUMN judgment_rule_config.orphan_object_minutes IS '고아 객체 유효기간(분). MinIO에만 있고 DB에 없는 경우. NULL이면 orphan_object_days*1440 사용';
COMMENT ON COLUMN judgment_rule_config.expired_candidate_minutes IS '만료 후보 유효기간(분). submission만 있고 receipt_items 없음. NULL이면 expired_candidate_days*1440 사용';

-- 2) VERIFYING/PENDING_VERIFICATION 대기 시간 초과 시 자동 처리 정책
ALTER TABLE judgment_rule_config
ADD COLUMN IF NOT EXISTS verifying_timeout_minutes INTEGER NOT NULL DEFAULT 0;

ALTER TABLE judgment_rule_config
ADD COLUMN IF NOT EXISTS verifying_timeout_action VARCHAR(16) NOT NULL DEFAULT 'UNFIT';

COMMENT ON COLUMN judgment_rule_config.verifying_timeout_minutes IS 'VERIFYING/PENDING_VERIFICATION 대기 허용 시간(분). 0이면 비활성. 초과 시 verifying_timeout_action 적용 후 콜백';
COMMENT ON COLUMN judgment_rule_config.verifying_timeout_action IS '대기 시간 초과 시 적용: UNFIT | ERROR';

-- 3) submissions.updated_at: VERIFYING 진입 시점 등 판단용
ALTER TABLE submissions
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();

UPDATE submissions SET updated_at = created_at WHERE updated_at IS NULL;

COMMENT ON COLUMN submissions.updated_at IS '최종 상태 변경 시각. VERIFYING 타임아웃 판단 등에 사용';
