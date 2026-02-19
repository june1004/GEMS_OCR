-- receipts 테이블에 address 컬럼 추가 (OCR 가맹점 주소 전체, PRD 자산화)
-- 적용: gems DB 접속(\c gems) 후 실행

ALTER TABLE receipts ADD COLUMN IF NOT EXISTS address VARCHAR(512);
