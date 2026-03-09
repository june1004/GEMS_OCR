-- TOUR 영수증 최대 3매, STAY 영수증 1매+인보이스 1매 제한 적용을 위한 Presigned 발급 횟수 컬럼
-- 실행: DBeaver에서 해당 DB 연결 선택 후 스크립트 전체 실행 (맥: Cmd+A → Cmd+Enter)

ALTER TABLE submissions
ADD COLUMN IF NOT EXISTS presigned_issued_count INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN submissions.presigned_issued_count IS 'Presigned URL 발급 횟수. TOUR 3매, STAY 2매 초과 시 400';
