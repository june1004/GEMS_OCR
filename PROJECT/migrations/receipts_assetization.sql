-- receipts 테이블 데이터 자산화 고도화
-- - image_key: MinIO 객체 키(영수증 이미지 경로)
-- - ocr_raw: 네이버 OCR JSON 전문 (JSONB)
-- - business_num: OCR에서 추출한 사업자등록번호
-- - GIN 인덱스: ocr_raw 기반 분석/검색 성능 향상
-- 적용: gems DB 접속(\c gems) 후 실행

ALTER TABLE receipts ADD COLUMN IF NOT EXISTS image_key TEXT;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS business_num TEXT;

-- ocr_raw 컬럼을 JSONB로 변환 (이미 JSONB이면 no-op)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'receipts' AND column_name = 'ocr_raw'
    ) THEN
        BEGIN
            ALTER TABLE receipts
                ALTER COLUMN ocr_raw
                SET DATA TYPE JSONB
                USING ocr_raw::jsonb;
        EXCEPTION
            WHEN others THEN
                -- 이미 JSONB이거나 변환 불가한 데이터가 있을 경우는 무시
                NULL;
        END;
    END IF;
END $$;

-- JSONB 전체에 대한 GIN 인덱스 (키/값 검색용)
CREATE INDEX IF NOT EXISTS idx_receipts_ocr_jsonb ON receipts USING GIN (ocr_raw);

