-- MinIO–DB 정합: 고아 객체/만료 후보 유효일(일). 관리자 설정, 기본 1일
-- 적용 DB: gems

ALTER TABLE judgment_rule_config
ADD COLUMN IF NOT EXISTS orphan_object_days INTEGER NOT NULL DEFAULT 1;

ALTER TABLE judgment_rule_config
ADD COLUMN IF NOT EXISTS expired_candidate_days INTEGER NOT NULL DEFAULT 1;

COMMENT ON COLUMN judgment_rule_config.orphan_object_days IS '고아 객체 유효일(일). MinIO에만 있고 DB에 없는 경우';
COMMENT ON COLUMN judgment_rule_config.expired_candidate_days IS '만료 후보 유효일(일). submission만 있고 receipt_items 없음';
