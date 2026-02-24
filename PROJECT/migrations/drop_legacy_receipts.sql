-- 레거시 단일 테이블(receipts) 제거
-- 현재 운영 구조는 submissions(parent) + receipt_items(child) 1:N 모델을 사용
-- 주의: 실행 전 백업 권장

DROP TABLE IF EXISTS receipts;
