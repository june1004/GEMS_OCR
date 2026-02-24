-- receipts 테이블: FE 연동(합산형 TOUR/STAY) 필수 컬럼
-- - image_key: 단일 이미지 객체 키 (하위호환)
-- - image_keys: 복수 이미지 (TOUR 1~3장 등), PostgreSQL TEXT[]
-- - documents: 신규 스펙 [{ imageKey, docType }]
-- 적용: gems DB 접속(\c gems) 후 실행
-- 참고: image_keys가 이미 JSONB로 있으면 ADD COLUMN은 스킵됨. 그 경우 BE는 Column(ARRAY(String)) 대신 Column(JSON) 사용 필요.

ALTER TABLE receipts ADD COLUMN IF NOT EXISTS image_key VARCHAR(500);
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS image_keys TEXT[];
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS documents JSONB;

-- BE 모델과 스키마 정합성용: 나머지 누락 컬럼 일괄 추가 (이미 있으면 스킵)
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS business_num VARCHAR(50);
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS ocr_assets JSONB;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS audit_trail TEXT;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS submission_type VARCHAR(50);

-- 적용 후 확인용: 아래 쿼리로 image_key, image_keys, documents 포함 여부 확인
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_schema = 'public' AND table_name = 'receipts'
-- ORDER BY ordinal_position;
