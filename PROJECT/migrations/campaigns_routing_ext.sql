-- campaigns 테이블 확장: 라우팅 우선순위/프로젝트 타입/updated_at
-- 기존 campaigns_filtering.sql(기본 캠페인 필터)와 호환되도록 "컬럼 추가"만 수행

BEGIN;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'campaigns') THEN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'campaigns' AND column_name = 'priority') THEN
      ALTER TABLE campaigns ADD COLUMN priority INTEGER NOT NULL DEFAULT 100;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'campaigns' AND column_name = 'project_type') THEN
      ALTER TABLE campaigns ADD COLUMN project_type VARCHAR(16);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'campaigns' AND column_name = 'updated_at') THEN
      ALTER TABLE campaigns ADD COLUMN updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW();
    END IF;
  END IF;
END $$;

COMMIT;

