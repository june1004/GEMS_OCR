import os
import pandas as pd
from sqlalchemy import create_engine, text
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv()

# 쿨리파이 환경변수를 자동으로 가져옵니다.
DB_URL = os.getenv("DATABASE_URL")
# Coolify/Heroku 등 postgres:// → SQLAlchemy 2.x 호환 (postgresql+psycopg2)
if DB_URL:
    if DB_URL.startswith("postgres://"):
        DB_URL = "postgresql+psycopg2://" + DB_URL[11:]
    elif DB_URL.startswith("postgresql://") and "+psycopg2" not in DB_URL:
        DB_URL = DB_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
FILE_NAME = "gangwon_20251217.csv"  # UTF-8 (원본 CP949에서 변환)

def _db_info(url: str) -> str:
    """비밀번호 제외 연결 정보 (확인용)"""
    try:
        parsed = urlparse(url.replace("postgresql+psycopg2://", "postgres://"))
        host = parsed.hostname or "?"
        db = (parsed.path or "/").strip("/") or "?"
        return f"host={host} database={db}"
    except Exception:
        return "?"

def run():
    if not DB_URL:
        print("❌ DATABASE_URL 환경 변수가 없습니다.")
        return
    try:
        # 1. 데이터 읽기 (UTF-8)
        df = pd.read_csv(FILE_NAME, encoding="utf-8")
        
        # 2. DB 컬럼명 매핑
        df_db = pd.DataFrame()
        df_db["store_name"] = df["업소명"]
        df_db["category_large"] = df["업종"]
        df_db["category_small"] = df["업태"]
        df_db["road_address"] = df["도로명주소"]
        
        engine = create_engine(DB_URL)
        print(f"📌 연결 DB: {_db_info(DB_URL)}")
        
        # 3. 테이블을 CSV 기준으로 교체 (재실행 시 중복 없음)
        df_db.to_sql(
            "master_stores",
            engine,
            if_exists="replace",  # 매 실행 시 기존 데이터 삭제 후 CSV로 교체 → 중복 없음
            index=False,
            method="multi",
            chunksize=1000,
        )
        
        # 4. 실제 DB에서 행 수 확인
        with engine.connect() as conn:
            r = conn.execute(text("SELECT COUNT(*) FROM master_stores"))
            total = r.scalar()
        print(f"✅ master_stores를 CSV 기준으로 교체했습니다. 총 {total}건 (재실행해도 중복 없음)")
    except Exception as e:
        print(f"❌ 에러 발생: {e}")
        raise

if __name__ == "__main__":
    run()