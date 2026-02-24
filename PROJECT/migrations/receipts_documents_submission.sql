-- 합산형 제출(Submission) 고도화 컬럼
-- 적용: gems DB 접속(\c gems) 후 실행

ALTER TABLE receipts ADD COLUMN IF NOT EXISTS image_keys JSONB;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS documents JSONB;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS ocr_assets JSONB;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS audit_trail TEXT;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS submission_type VARCHAR(50);

-- 검색/분석 성능용 인덱스
CREATE INDEX IF NOT EXISTS idx_receipts_image_keys_gin ON receipts USING GIN (image_keys);
CREATE INDEX IF NOT EXISTS idx_receipts_documents_gin ON receipts USING GIN (documents);
CREATE INDEX IF NOT EXISTS idx_receipts_ocr_assets_gin ON receipts USING GIN (ocr_assets);
