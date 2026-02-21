-- 캠페인 필터링: 지역·기간 제한 (강원 18개 시군구 축제/이벤트 확장)
-- target_city_county NULL = 강원 전체, 값 있으면 해당 시군만 인정
-- start_date / end_date NULL이면 기간 제한 없음
--
-- [gems DB 실행 방법]
--   로컬:  psql "postgresql://USER:PASSWORD@HOST:5432/gems" -f PROJECT/migrations/campaigns_filtering.sql
--   예시:  psql "postgresql://postgres:password@localhost:5432/gems" -f PROJECT/migrations/campaigns_filtering.sql
--   .env:  psql "$DATABASE_URL" -f PROJECT/migrations/campaigns_filtering.sql
--   (단, DATABASE_URL이 postgresql+psycopg2:// 이면 postgresql:// 로 바꾼 뒤 사용)

CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id   SERIAL PRIMARY KEY,
    campaign_name VARCHAR(255),
    is_active     BOOLEAN DEFAULT true,
    target_city_county VARCHAR(50),
    start_date    DATE,
    end_date      DATE,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 기존 테이블에 컬럼만 추가하는 경우 (테이블이 이미 있을 때)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'campaigns') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'campaigns' AND column_name = 'target_city_county') THEN
            ALTER TABLE campaigns ADD COLUMN target_city_county VARCHAR(50);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'campaigns' AND column_name = 'start_date') THEN
            ALTER TABLE campaigns ADD COLUMN start_date DATE;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'campaigns' AND column_name = 'end_date') THEN
            ALTER TABLE campaigns ADD COLUMN end_date DATE;
        END IF;
    END IF;
END $$;

-- 기본 캠페인 1건 (강원 전체, 기간 제한 없음) — 없을 때만 삽입
INSERT INTO campaigns (campaign_name, is_active, target_city_county, start_date, end_date)
SELECT '2026 혜택받go 강원 여행 인센티브', true, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM campaigns LIMIT 1);

-- 예시: 춘천시 전용 캠페인 (필요 시 실행)
-- INSERT INTO campaigns (campaign_name, is_active, target_city_county, start_date, end_date)
-- VALUES ('2026 춘천 막국수 닭갈비 축제 인센티브', true, '춘천시', '2026-05-01', '2026-05-31');
