#!/usr/bin/env python3
"""
receipts 테이블 FE 연동용 컬럼 마이그레이션 (Coolify 등 psql 없는 환경용).
DATABASE_URL 환경 변수로 DB에 접속해 PROJECT/migrations/receipts_fe_columns.sql 실행.
사용: python run_receipts_migration.py
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL 환경 변수가 없습니다.")
    exit(1)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[11:]
elif DATABASE_URL.startswith("postgresql://") and "+psycopg2" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

ROOT = Path(__file__).resolve().parent
SQL_PATH = ROOT / "PROJECT" / "migrations" / "receipts_fe_columns.sql"

if not SQL_PATH.exists():
    print(f"❌ SQL 파일 없음: {SQL_PATH}")
    exit(1)

SQL = SQL_PATH.read_text(encoding="utf-8")
# 주석/빈 줄 제거 후, 세미콜론으로 구분된 문장만 추출 (ALTER/CREATE만 실행)
lines = [line.strip() for line in SQL.splitlines() if line.strip() and not line.strip().startswith("--")]
full = " ".join(lines)
statements = [s.strip() for s in full.split(";") if s.strip()]
to_run = [
    s for s in statements
    if s.upper().startswith("ALTER ") or s.upper().startswith("CREATE ")
]


def main():
    engine = create_engine(DATABASE_URL)
    print(f"📌 DB 연결 후 마이그레이션 실행: {SQL_PATH.name}")
    with engine.begin() as conn:
        for i, stmt in enumerate(to_run, 1):
            try:
                conn.execute(text(stmt))
                if "ADD COLUMN IF NOT EXISTS" in stmt:
                    parts = stmt.split("ADD COLUMN IF NOT EXISTS")[-1].strip().split()
                    col = parts[0] if parts else stmt[:50]
                    print(f"  [{i}] OK: {col}")
                else:
                    print(f"  [{i}] OK: {stmt[:55]}...")
            except Exception as e:
                print(f"  [{i}] ⚠️ {e}")
                raise
    print("✅ receipts_fe_columns.sql 적용 완료.")


if __name__ == "__main__":
    main()
