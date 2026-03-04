-- FE 제출 시 사용자 입력 스냅샷 저장 (검수 시 비교·관리자 상세 노출용)
-- 적용 DB: gems

ALTER TABLE submissions
ADD COLUMN IF NOT EXISTS user_input_snapshot JSONB;

COMMENT ON COLUMN submissions.user_input_snapshot IS 'Complete 요청 시 FE가 보낸 data (방식2: items 배열). 관리자 상세 API에서 반환';
