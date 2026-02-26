-- 판정 규칙 운영 설정 테이블
-- 관리자 화면에서 수정 가능한 BE 판정 정책

CREATE TABLE IF NOT EXISTS judgment_rule_config (
    id INTEGER PRIMARY KEY,
    unknown_store_policy VARCHAR(32) NOT NULL DEFAULT 'AUTO_REGISTER', -- AUTO_REGISTER | PENDING_NEW
    auto_register_threshold FLOAT NOT NULL DEFAULT 0.90,               -- 0.0 ~ 1.0
    enable_gemini_classifier BOOLEAN NOT NULL DEFAULT true,
    min_amount_stay INTEGER NOT NULL DEFAULT 60000,
    min_amount_tour INTEGER NOT NULL DEFAULT 50000,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- 단일 설정 행(싱글톤) 보장: id=1
INSERT INTO judgment_rule_config (
    id, unknown_store_policy, auto_register_threshold, enable_gemini_classifier, min_amount_stay, min_amount_tour
)
SELECT 1, 'AUTO_REGISTER', 0.90, true, 60000, 50000
WHERE NOT EXISTS (SELECT 1 FROM judgment_rule_config WHERE id = 1);

