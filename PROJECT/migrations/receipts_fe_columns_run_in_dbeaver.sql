-- DBeaver에서 "전체 선택(Ctrl+A)" 후 "실행(Ctrl+Enter)" 해서 한 번에 적용하세요.
-- (한 줄만 실행하면 나머지 컬럼이 추가되지 않습니다.)

ALTER TABLE receipts ADD COLUMN IF NOT EXISTS image_key VARCHAR(500);
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS image_keys TEXT[];
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS documents JSONB;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS business_num VARCHAR(50);
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS ocr_assets JSONB;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS audit_trail TEXT;
