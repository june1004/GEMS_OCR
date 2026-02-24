-- receipts 테이블 스키마 확인용 (실행만 하고 결과만 보면 됨)
-- FE 연동에 필요한 컬럼: image_key, image_keys, documents

SELECT column_name, data_type, character_maximum_length, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'receipts'
ORDER BY ordinal_position;
