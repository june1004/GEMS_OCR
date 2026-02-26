-- 자산화/외부표시 필드 값 정규화 (기존 데이터 백필)
-- 대상: receipt_items.biz_num, unregistered_stores.biz_num/tel/address
-- 주의: 실행 전 DB 백업 권장. (값을 덮어씀)

-- 1) 사업자등록번호: 숫자 10자리면 000-00-00000 포맷
WITH ri AS (
  SELECT item_id, regexp_replace(COALESCE(biz_num,''), '[^0-9]', '', 'g') AS d
  FROM receipt_items
)
UPDATE receipt_items r
SET biz_num = CASE
  WHEN length(ri.d) = 10 THEN substr(ri.d,1,3) || '-' || substr(ri.d,4,2) || '-' || substr(ri.d,6,5)
  ELSE NULLIF(trim(r.biz_num), '')
END
FROM ri
WHERE r.item_id = ri.item_id;

WITH us AS (
  SELECT id,
         regexp_replace(COALESCE(biz_num,''), '[^0-9]', '', 'g') AS biz_d,
         regexp_replace(COALESCE(tel,''), '[^0-9]', '', 'g') AS tel_d
  FROM unregistered_stores
)
UPDATE unregistered_stores u
SET biz_num = CASE
    WHEN length(us.biz_d) = 10 THEN substr(us.biz_d,1,3) || '-' || substr(us.biz_d,4,2) || '-' || substr(us.biz_d,6,5)
    ELSE NULLIF(trim(u.biz_num), '')
  END,
  tel = CASE
    WHEN us.tel_d = '' THEN NULLIF(trim(u.tel), '')
    WHEN us.tel_d LIKE '82%' AND length(us.tel_d) >= 10 THEN
      -- 82로 시작하면 0으로 치환 후 아래 규칙 적용
      NULL
    WHEN length(us.tel_d) = 8 THEN substr(us.tel_d,1,4) || '-' || substr(us.tel_d,5,4)
    WHEN us.tel_d LIKE '02%' AND length(us.tel_d) = 9 THEN '02-' || substr(us.tel_d,3,3) || '-' || substr(us.tel_d,6,4)
    WHEN us.tel_d LIKE '02%' AND length(us.tel_d) = 10 THEN '02-' || substr(us.tel_d,3,4) || '-' || substr(us.tel_d,7,4)
    WHEN length(us.tel_d) = 10 THEN substr(us.tel_d,1,3) || '-' || substr(us.tel_d,4,3) || '-' || substr(us.tel_d,7,4)
    WHEN length(us.tel_d) = 11 THEN substr(us.tel_d,1,3) || '-' || substr(us.tel_d,4,4) || '-' || substr(us.tel_d,8,4)
    ELSE NULLIF(trim(u.tel), '')
  END,
  address = CASE
    WHEN u.address IS NULL OR trim(u.address) = '' THEN NULL
    ELSE regexp_replace(regexp_replace(trim(u.address), '\s+', ' ', 'g'), '^강원도(\s+)', '강원특별자치도\\1')
  END
FROM us
WHERE u.id = us.id;

-- 2) 국제코드 82로 시작하는 전화번호 처리 (0 + 나머지)
WITH us2 AS (
  SELECT id,
         ('0' || substr(regexp_replace(COALESCE(tel,''), '[^0-9]', '', 'g'), 3)) AS d
  FROM unregistered_stores
  WHERE regexp_replace(COALESCE(tel,''), '[^0-9]', '', 'g') LIKE '82%'
)
UPDATE unregistered_stores u
SET tel = CASE
    WHEN length(us2.d) = 8 THEN substr(us2.d,1,4) || '-' || substr(us2.d,5,4)
    WHEN us2.d LIKE '02%' AND length(us2.d) = 9 THEN '02-' || substr(us2.d,3,3) || '-' || substr(us2.d,6,4)
    WHEN us2.d LIKE '02%' AND length(us2.d) = 10 THEN '02-' || substr(us2.d,3,4) || '-' || substr(us2.d,7,4)
    WHEN length(us2.d) = 10 THEN substr(us2.d,1,3) || '-' || substr(us2.d,4,3) || '-' || substr(us2.d,7,4)
    WHEN length(us2.d) = 11 THEN substr(us2.d,1,3) || '-' || substr(us2.d,4,4) || '-' || substr(us2.d,8,4)
    ELSE NULLIF(trim(u.tel), '')
  END
FROM us2
WHERE u.id = us2.id;

