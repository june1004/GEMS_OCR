import pandas as pd
from sqlalchemy import create_engine
import os

# 쿨리파이 환경변수를 자동으로 가져옵니다.
DB_URL = os.getenv("DATABASE_URL") 
FILE_NAME = "gangwon_20251217.csv"  # UTF-8 (원본 CP949에서 변환)

def run():
    try:
        # 1. 데이터 읽기 (UTF-8)
        df = pd.read_csv(FILE_NAME, encoding="utf-8")
        
        # 2. DB 컬럼명 매핑
        df_db = pd.DataFrame()
        df_db['store_name'] = df['업소명']
        df_db['category_large'] = df['업종']
        df_db['category_small'] = df['업태']
        df_db['road_address'] = df['도로명주소']
        
        # 3. DB 연결 및 삽입
        engine = create_engine(DB_URL)
        df_db.to_sql('master_stores', engine, if_exists='append', index=False)
        
        print(f"✅ 총 {len(df_db)}건의 상점 데이터를 업로드했습니다!")
    except Exception as e:
        print(f"❌ 에러 발생: {e}")

if __name__ == "__main__":
    run()