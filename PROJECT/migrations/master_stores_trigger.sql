-- master_stores: 누락 컬럼 추가 및 주소 파싱 트리거
-- 적용 순서: 1) migrate.py 실행 후, 2) gems DB 접속(\c gems), 3) 본 파일 실행

-- 1단계: 누락된 컬럼 추가
ALTER TABLE master_stores ADD COLUMN IF NOT EXISTS city_county VARCHAR(50);
ALTER TABLE master_stores ADD COLUMN IF NOT EXISTS hometax_status VARCHAR(20) DEFAULT 'UNKNOWN';
ALTER TABLE master_stores ADD COLUMN IF NOT EXISTS last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- 2단계: 주소 자동 분류 트리거
CREATE OR REPLACE FUNCTION fn_update_city_county_auto()
RETURNS TRIGGER AS $$
BEGIN
    NEW.city_county := (string_to_array(NEW.road_address, ' '))[2];
    NEW.last_updated := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_master_stores_parse_address ON master_stores;
CREATE TRIGGER trg_master_stores_parse_address
BEFORE INSERT OR UPDATE OF road_address ON master_stores
FOR EACH ROW EXECUTE PROCEDURE fn_update_city_county_auto();

-- 3단계: 기존 데이터에 시군 정보 채우기 (migrate.py로 넣은 데이터용)
UPDATE master_stores SET road_address = road_address;
