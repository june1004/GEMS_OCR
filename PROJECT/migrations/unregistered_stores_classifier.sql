-- 업종 자동 분류 알고리즘용 컬럼 (Smart Classifier)
-- category_confidence: 분류 신뢰도 0.0 ~ 1.0
-- classifier_type: RULE | SEMANTIC | AI (Gemini)
-- status 'AUTO_REGISTERED': 룰/AI 고신뢰도로 자동 분류·마스터 편입된 경우

ALTER TABLE unregistered_stores ADD COLUMN IF NOT EXISTS category_confidence FLOAT;
ALTER TABLE unregistered_stores ADD COLUMN IF NOT EXISTS classifier_type VARCHAR(20);

-- COMMENT for future self-learning / 지자체별 설정 시 참고
COMMENT ON COLUMN unregistered_stores.category_confidence IS '0.0~1.0. 0.9 이상이면 자동 마스터 편입 후보';
COMMENT ON COLUMN unregistered_stores.classifier_type IS 'RULE | SEMANTIC | AI';
