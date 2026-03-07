#!/usr/bin/env python3
"""
최초 슈퍼관리자 1명 생성. 환경변수 JWT_SECRET, SUPER_ADMIN_EMAIL, SUPER_ADMIN_PASSWORD 필요.
비밀번호 정책: 영문 대소문자 1자 이상, 숫자, 특수문자, 8자 이상.
사용 예: SUPER_ADMIN_EMAIL=admin@example.com SUPER_ADMIN_PASSWORD='Abc1!xyz' python PROJECT/scripts/create_super_admin.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("DATABASE_URL", os.getenv("DATABASE_URL", ""))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext

PASSWORD_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_\-+=[\]{}|;:'\",.<>?/\\`~])[A-Za-z\d!@#$%^&*()_\-+=[\]{}|;:'\",.<>?/\\`~]{8,}$"
)

def main():
    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL not set")
        sys.exit(1)
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[11:]
    email = (os.getenv("SUPER_ADMIN_EMAIL") or "").strip().lower()
    password = os.getenv("SUPER_ADMIN_PASSWORD", "")
    if not email or not password:
        print("SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD required")
        sys.exit(1)
    if not PASSWORD_PATTERN.match(password):
        print("Password must: 8+ chars, upper+lower+digit+special")
        sys.exit(1)
    engine = create_engine(url)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        r = db.execute(text("SELECT id FROM admin_users WHERE LOWER(email) = :e"), {"e": email}).fetchone()
        if r:
            print("Super admin already exists for", email)
            return
        h = CryptContext(schemes=["bcrypt"], deprecated="auto").hash(password)
        db.execute(
            text(
                "INSERT INTO admin_users (email, password_hash, role, is_active) VALUES (:e, :h, 'SUPER_ADMIN', true)"
            ),
            {"e": email, "h": h},
        )
        db.commit()
        print("Super admin created:", email)
    finally:
        db.close()

if __name__ == "__main__":
    main()
