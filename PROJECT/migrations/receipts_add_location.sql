-- receipts 테이블에 location 컬럼 추가 (main.py Receipt 모델과 동기화)
-- 적용: gems DB 접속(\c gems) 후 실행

ALTER TABLE receipts ADD COLUMN IF NOT EXISTS location VARCHAR(255);
