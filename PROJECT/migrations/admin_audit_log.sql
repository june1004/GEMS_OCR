-- 관리자 감사로그 (운영 추적용)
-- 누가/언제/무엇을/어떻게 바꿨는지 기록

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id BIGSERIAL PRIMARY KEY,
    actor VARCHAR(128),                 -- 관리자 식별자(이메일/계정ID/IP 등)
    action VARCHAR(64) NOT NULL,        -- RULE_UPDATE | CANDIDATE_APPROVE | SUBMISSION_OVERRIDE | CALLBACK_RESEND | CAMPAIGN_CREATE | CAMPAIGN_UPDATE
    target_type VARCHAR(64),            -- judgment_rule_config | unregistered_store | submission
    target_id VARCHAR(128),             -- receiptId, candidate_id 등
    before_json JSONB,
    after_json JSONB,
    meta JSONB,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_action ON admin_audit_log (action);
CREATE INDEX IF NOT EXISTS idx_admin_audit_log_target ON admin_audit_log (target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_admin_audit_log_created_at ON admin_audit_log (created_at);

