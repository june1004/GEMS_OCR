-- submission_items 테이블 제거 (미사용 시)
-- 현재 스키마는 submissions + receipt_items (1:N) 사용. submission_items는 코드에서 참조 없음.
-- 실행: psql "$DATABASE_URL" -f PROJECT/migrations/drop_submission_items_if_unused.sql

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = current_schema() AND table_name = 'submission_items'
  ) THEN
    DROP TABLE submission_items;
    RAISE NOTICE 'Dropped table submission_items (unused).';
  ELSE
    RAISE NOTICE 'Table submission_items does not exist, nothing to drop.';
  END IF;
END $$;
