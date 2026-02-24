-- 1:N 상속형 영수증 구조
-- parent: submissions / child: receipt_items
-- 적용 DB: gems

CREATE TABLE IF NOT EXISTS submissions (
    submission_id VARCHAR(64) PRIMARY KEY,
    user_uuid VARCHAR(128) NOT NULL,
    project_type VARCHAR(16) NOT NULL, -- STAY | TOUR
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    total_amount INTEGER,
    fail_reason VARCHAR(255),
    audit_log TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS receipt_items (
    item_id VARCHAR(64) PRIMARY KEY,
    submission_id VARCHAR(64) NOT NULL REFERENCES submissions(submission_id) ON DELETE CASCADE,
    seq_no INTEGER NOT NULL DEFAULT 1,
    doc_type VARCHAR(32) NOT NULL DEFAULT 'RECEIPT',
    image_key VARCHAR(500) NOT NULL,
    store_name VARCHAR(255),
    biz_num VARCHAR(64),
    pay_date VARCHAR(32),
    amount INTEGER,
    address VARCHAR(500),
    location VARCHAR(255),
    card_num VARCHAR(4) NOT NULL DEFAULT '0000',
    confidence_score INTEGER,
    ocr_raw JSONB,
    parsed JSONB,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- 기존 테이블 호환 (이미 생성된 경우 누락 컬럼 보강)
ALTER TABLE receipt_items ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'PENDING';
ALTER TABLE receipt_items ADD COLUMN IF NOT EXISTS error_code VARCHAR(64);
ALTER TABLE receipt_items ADD COLUMN IF NOT EXISTS error_message VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_submissions_user_uuid ON submissions(user_uuid);
CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);
CREATE INDEX IF NOT EXISTS idx_receipt_items_submission_id ON receipt_items(submission_id);
CREATE INDEX IF NOT EXISTS idx_receipt_items_dupcheck ON receipt_items(biz_num, pay_date, amount, card_num);
CREATE INDEX IF NOT EXISTS idx_receipt_items_ocr_raw_gin ON receipt_items USING GIN (ocr_raw);
