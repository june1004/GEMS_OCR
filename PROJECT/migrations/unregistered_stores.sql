-- 마스터 미등록 상점 임시 등록 테이블
-- status: TEMP_VALID | APPROVED | REJECTED

CREATE TABLE IF NOT EXISTS unregistered_stores (
    id VARCHAR(64) PRIMARY KEY,
    store_name VARCHAR(255),
    biz_num VARCHAR(64),
    address VARCHAR(500),
    tel VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'TEMP_VALID',
    source_submission_id VARCHAR(64),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_unregistered_stores_biz_num ON unregistered_stores (biz_num);
CREATE INDEX IF NOT EXISTS idx_unregistered_stores_status ON unregistered_stores (status);
CREATE INDEX IF NOT EXISTS idx_unregistered_stores_source_submission ON unregistered_stores (source_submission_id);

-- 중복 완화를 위한 유니크 인덱스 (NULL 허용 컬럼 조합 대응)
CREATE UNIQUE INDEX IF NOT EXISTS uq_unregistered_stores_biz_addr_tel
ON unregistered_stores (
    COALESCE(biz_num, ''),
    COALESCE(address, ''),
    COALESCE(tel, '')
);
