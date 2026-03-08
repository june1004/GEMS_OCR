-- ============================================================
-- 회원가입 대기(pending_signups) 테이블 — 맥 DBeaver: Cmd+A → 스크립트 실행
-- ============================================================
-- signup API로 저장된 가입 신청을 관리자 승인(approve) 시 admin_users로 이전합니다.

-- [1] pending_signups
CREATE TABLE IF NOT EXISTS pending_signups (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(255) NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    phone           VARCHAR(64),
    org_type        VARCHAR(32)  NOT NULL,
    sido_code       VARCHAR(8),
    sido_name       VARCHAR(128),
    sigungu_code    VARCHAR(16),
    sigungu_name    VARCHAR(128),
    org_name        VARCHAR(255),
    department      VARCHAR(255),
    status          VARCHAR(16)  NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_signups_email ON pending_signups(LOWER(email));
CREATE INDEX IF NOT EXISTS idx_pending_signups_status ON pending_signups(status);

-- [2] admin_users에 name, org_name 컬럼 추가 (승인 시 반영용)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'admin_users') THEN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'admin_users' AND column_name = 'name') THEN
      ALTER TABLE admin_users ADD COLUMN name VARCHAR(255);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'admin_users' AND column_name = 'org_name') THEN
      ALTER TABLE admin_users ADD COLUMN org_name VARCHAR(255);
    END IF;
  END IF;
END $$;
