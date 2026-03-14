-- 운영 컨텍스트: 사용자당 마지막 선택 캠페인 1건 (PUT /admin/context 저장, GET /admin/context·/admin/me 응답 projectId 반환)
-- 실행: psql "$DATABASE_URL" -f PROJECT/migrations/admin_user_last_selected_campaign.sql

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'admin_users') THEN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'admin_users' AND column_name = 'last_selected_campaign_id') THEN
      ALTER TABLE admin_users ADD COLUMN last_selected_campaign_id INTEGER NULL;
      RAISE NOTICE 'Added admin_users.last_selected_campaign_id';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'admin_users' AND column_name = 'last_selected_project_id') THEN
      ALTER TABLE admin_users ADD COLUMN last_selected_project_id INTEGER NULL;
      RAISE NOTICE 'Added admin_users.last_selected_project_id';
    END IF;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'admin_users' AND column_name = 'last_selected_campaign_id') THEN
    EXECUTE 'COMMENT ON COLUMN admin_users.last_selected_campaign_id IS ''담당자 운영 컨텍스트: 마지막 선택 캠페인 ID (PUT /admin/context)''';
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'admin_users' AND column_name = 'last_selected_project_id') THEN
    EXECUTE 'COMMENT ON COLUMN admin_users.last_selected_project_id IS ''담당자 운영 컨텍스트: 마지막 선택 프로젝트 ID (PUT /admin/context)''';
  END IF;
END $$;
