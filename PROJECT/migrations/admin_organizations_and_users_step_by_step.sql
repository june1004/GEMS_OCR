-- ============================================================
-- DBeaver 실행 방법 (순서 지키기!) — 맥 기준
-- ============================================================
-- 1) campaigns 테이블이 있는 DB(gems 등)에 연결
-- 2) 이 파일 "전체"를 선택한 뒤 한 번에 실행:
--    맥: Cmd+A (전체 선택) → Cmd+Enter 또는 메뉴 [SQL 편집기] → [스크립트 실행]
--    윈도우: Ctrl+A → F5 또는 [Execute SQL Script]
--    → 반드시 위에서 아래 순서로 실행되어야 함.
-- 3) 아래 순서를 바꾸거나, 일부만 선택해서 실행하면 FK 오류 발생:
--    [1단계] organizations → [2단계] admin_users → [3단계] admin_campaign_access → [4단계] campaigns 컬럼
-- ============================================================

-- [1단계] 기관 테이블 (가장 먼저)
CREATE TABLE IF NOT EXISTS organizations (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    sido_code   VARCHAR(8)   NOT NULL,
    sigungu_code VARCHAR(16),
    created_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_organizations_sido_sigungu ON organizations(sido_code, sigungu_code);

-- [2단계] 관리자(담당자) 테이블 (organizations 참조)
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

-- [3단계] 담당자-캠페인 접근 권한 테이블 (admin_users 참조)
CREATE TABLE IF NOT EXISTS admin_campaign_access (
    admin_user_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    campaign_id   INTEGER NOT NULL,
    created_at    TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (admin_user_id, campaign_id)
);
CREATE INDEX IF NOT EXISTS idx_admin_campaign_access_campaign ON admin_campaign_access(campaign_id);

-- [4단계] (선택) campaigns에 기관 FK 추가 — campaigns 테이블이 있을 때만. 이미 있으면 무시.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'campaigns') THEN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'campaigns' AND column_name = 'organization_id') THEN
      ALTER TABLE campaigns ADD COLUMN organization_id INTEGER REFERENCES organizations(id);
    END IF;
  END IF;
END $$;
