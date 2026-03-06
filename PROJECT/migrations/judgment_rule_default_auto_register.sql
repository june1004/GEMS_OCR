-- 신규상점검수대기(PENDING_NEW) → 자동 상점추가(AUTO_REGISTER) 기본값 통일
-- 데이터 자산화·관리: 미등록 상점을 자동으로 master_stores + unregistered_stores에 등록하도록 기본 정책 설정
-- 적용 DB: gems

-- 기존 행이 NULL 이거나 PENDING_NEW 이면 AUTO_REGISTER 로 변경
UPDATE judgment_rule_config
SET unknown_store_policy = 'AUTO_REGISTER',
    updated_at = COALESCE(updated_at, NOW())
WHERE id = 1
  AND (unknown_store_policy IS NULL OR unknown_store_policy = 'PENDING_NEW');

-- 신규 INSERT 시 기본값 명시 (이미 컬럼 DEFAULT 있으면 생략 가능)
COMMENT ON COLUMN judgment_rule_config.unknown_store_policy IS 'AUTO_REGISTER=자동 상점추가(기본, 데이터 자산화) | PENDING_NEW=신규상점 검수 대기';
