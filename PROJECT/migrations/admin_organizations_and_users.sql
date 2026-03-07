-- 슈퍼관리자·기관·캠페인별 담당자 권한 체계
-- 지자체(행정 시도/시군구)별 기관, 담당자 회원가입, 캠페인별 접근 권한
-- [실행] psql "$DATABASE_URL" -f PROJECT/migrations/admin_organizations_and_users.sql
-- (DATABASE_URL이 postgresql+psycopg2:// 이면 postgresql:// 로 바꾼 뒤 사용)

BEGIN;

-- 1) 기관 (지자체: 행정 시도/시군구 단위)
CREATE TABLE IF NOT EXISTS organizations (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    sido_code   VARCHAR(8)   NOT NULL,
    sigungu_code VARCHAR(16),
    created_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_organizations_sido_sigungu ON organizations(sido_code, sigungu_code);
COMMENT ON TABLE organizations IS '지자체(행정 시도/시군구)별 기관. 캠페인·담당자 소속 단위';

-- 2) 캠페인에 기관 연결 (선택)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'campaigns') THEN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'campaigns' AND column_name = 'organization_id') THEN
      ALTER TABLE campaigns ADD COLUMN organization_id INTEGER REFERENCES organizations(id);
    END IF;
  END IF;
END $$;

-- 3) 관리자(담당자) 계정: 로그인 ID = 이메일, 비밀번호 해시 저장
CREATE TABLE IF NOT EXISTS admin_users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    role            VARCHAR(32)  NOT NULL DEFAULT 'CAMPAIGN_ADMIN',
    organization_id INTEGER REFERENCES organizations(id),
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_users_email ON admin_users(LOWER(email));
COMMENT ON COLUMN admin_users.role IS 'SUPER_ADMIN | ORG_ADMIN | CAMPAIGN_ADMIN';
COMMENT ON TABLE admin_users IS '관리자(담당자). 이메일 로그인, 캠페인별 접근 권한은 admin_campaign_access';

-- 4) 담당자별 접근 가능 캠페인 (CAMPAIGN_ADMIN/ORG_ADMIN은 여기 있는 캠페인만 조회 가능)
CREATE TABLE IF NOT EXISTS admin_campaign_access (
    admin_user_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    campaign_id   INTEGER NOT NULL,
    created_at    TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (admin_user_id, campaign_id)
);
CREATE INDEX IF NOT EXISTS idx_admin_campaign_access_campaign ON admin_campaign_access(campaign_id);
COMMENT ON TABLE admin_campaign_access IS '담당자가 접근 가능한 캠페인. SUPER_ADMIN은 전체 접근(이 테이블 무시)';

COMMIT;
