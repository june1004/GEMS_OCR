-- 신규 상점 후보군 API용 컬럼 추가 (발생 빈도·증거 링크)
-- occurrence_count: 동일 상점(biz_num+address+tel) 영수증 접수 횟수
-- first_detected_at: 최초 발견 시각 (created_at과 동일 목적)
-- recent_receipt_id: 최근 증거 영수증 submission_id (관리자 확인용)
-- predicted_category: OCR/추후 분류용 (nullable)

ALTER TABLE unregistered_stores ADD COLUMN IF NOT EXISTS occurrence_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE unregistered_stores ADD COLUMN IF NOT EXISTS first_detected_at TIMESTAMP WITHOUT TIME ZONE;
ALTER TABLE unregistered_stores ADD COLUMN IF NOT EXISTS recent_receipt_id VARCHAR(64);
ALTER TABLE unregistered_stores ADD COLUMN IF NOT EXISTS predicted_category VARCHAR(64);

-- 기존 행: first_detected_at = created_at, recent_receipt_id = source_submission_id
UPDATE unregistered_stores
SET first_detected_at = COALESCE(first_detected_at, created_at),
    recent_receipt_id = COALESCE(recent_receipt_id, source_submission_id)
WHERE first_detected_at IS NULL OR recent_receipt_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_unregistered_stores_recent_receipt ON unregistered_stores (recent_receipt_id);
