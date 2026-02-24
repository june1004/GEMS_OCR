-- 1:N 구조 적용 확인용
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('submissions', 'receipt_items')
ORDER BY table_name, ordinal_position;
