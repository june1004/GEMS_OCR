-- 캠페인 예산(budget) 컬럼 추가 — 대시보드 "예산 소진 현황"용
-- 실행: psql "$DATABASE_URL" -f PROJECT/migrations/campaigns_budget.sql

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'campaigns') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'campaigns' AND column_name = 'budget') THEN
            ALTER TABLE campaigns ADD COLUMN budget BIGINT;
        END IF;
    END IF;
END $$;
