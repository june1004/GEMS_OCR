-- Override 시 콜백 재전송 옵션: 자동전송(AUTO) | 수동전송(MANUAL)
-- AUTO: override 실행 시 항상 영수증 FE로 콜백 전송
-- MANUAL: override 시 resend_callback: true 일 때만 전송
-- 실행: psql "$DATABASE_URL" -f PROJECT/migrations/judgment_rule_override_callback_policy.sql

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'judgment_rule_config') THEN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'judgment_rule_config' AND column_name = 'override_callback_policy') THEN
      ALTER TABLE judgment_rule_config ADD COLUMN override_callback_policy VARCHAR(16) DEFAULT 'AUTO';
      RAISE NOTICE 'Added judgment_rule_config.override_callback_policy (AUTO=자동전송, MANUAL=수동전송)';
    ELSE
      RAISE NOTICE 'Column judgment_rule_config.override_callback_policy already exists.';
    END IF;
  END IF;
END $$;

COMMENT ON COLUMN judgment_rule_config.override_callback_policy IS 'AUTO=override 시 콜백 자동전송, MANUAL=수동(재전송 체크/버튼 시에만)';

UPDATE judgment_rule_config SET override_callback_policy = 'AUTO' WHERE id = 1 AND (override_callback_policy IS NULL OR override_callback_policy = '');
