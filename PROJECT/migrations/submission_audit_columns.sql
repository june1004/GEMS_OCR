-- submissions.audit_trail / audit_log 컬럼 추가 (교정 API 등에서 사용, 구 스키마에 없을 수 있음)
-- 실행: psql "$DATABASE_URL" -f PROJECT/migrations/submission_audit_columns.sql

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'submissions') THEN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'submissions' AND column_name = 'audit_trail') THEN
      ALTER TABLE submissions ADD COLUMN audit_trail TEXT;
      RAISE NOTICE 'Added submissions.audit_trail';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'submissions' AND column_name = 'audit_log') THEN
      ALTER TABLE submissions ADD COLUMN audit_log TEXT;
      RAISE NOTICE 'Added submissions.audit_log';
    END IF;
  END IF;
END $$;
