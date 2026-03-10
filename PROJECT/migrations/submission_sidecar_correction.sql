-- 증거(영수증) 교정 이력 Sidecar JSON (§10 데이터 교정·AI 자산화)
-- GEMS 표준(GEMS_표준_수정_반려_사유_분류.md §6): receipt_id, ai_result, human_correction, asset_tag, correction_audit
-- 실행: psql "$DATABASE_URL" -f PROJECT/migrations/submission_sidecar_correction.sql

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'submissions') THEN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'submissions' AND column_name = 'submission_sidecar') THEN
      ALTER TABLE submissions ADD COLUMN submission_sidecar JSONB;
      RAISE NOTICE 'Added submissions.submission_sidecar (JSONB) for correction_audit, reviewer_correction, etc.';
    ELSE
      RAISE NOTICE 'Column submissions.submission_sidecar already exists.';
    END IF;
  END IF;
END $$;
