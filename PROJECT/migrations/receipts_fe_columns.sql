-- receipts 테이블: FE 연동(합산형 TOUR/STAY) 필수 컬럼
-- - image_key: 단일 이미지 객체 키 (하위호환)
-- - image_keys: 복수 이미지 (TOUR 1~3장 등), PostgreSQL TEXT[]
-- - documents: 신규 스펙 [{ imageKey, docType }]
-- 적용: gems DB 접속(\c gems) 후 실행
-- 참고: image_keys가 이미 JSONB로 있으면 ADD COLUMN은 스킵됨. 그 경우 BE는 Column(ARRAY(String)) 대신 Column(JSON) 사용 필요.

ALTER TABLE receipts ADD COLUMN IF NOT EXISTS image_key VARCHAR(500);
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS image_keys TEXT[];
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS documents JSONB;
