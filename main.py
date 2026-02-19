import os
import uuid
import json
import httpx
import boto3
import pandas as pd
from datetime import datetime
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy import Column, String, Integer, Float, DateTime, JSON, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from botocore.config import Config

# .env 파일 로드 (PROJECT/GEMS_PROJECT_GUIDE.md §4 환경 변수)
load_dotenv()

# 1. 초기 설정 및 환경 변수
app = FastAPI(title="GEMS OCR API", version="1.0.0")

DATABASE_URL = os.getenv("DATABASE_URL")
# Coolify/Heroku 등 postgres:// URL → SQLAlchemy 2.x 호환 (postgresql+psycopg2)
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[11:]  # postgres:// 제거 후 붙임
    elif DATABASE_URL.startswith("postgresql://") and "+psycopg2" not in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
S3_ENDPOINT = os.getenv("S3_ENDPOINT")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_BUCKET = os.getenv("S3_BUCKET")
NAVER_OCR_URL = os.getenv("NAVER_OCR_INVOKE_URL")
NAVER_OCR_SECRET = os.getenv("NAVER_OCR_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 데이터베이스 설정
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# S3 클라이언트 설정
s3_client = boto3.client(
    's3',
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    config=Config(signature_version='s3v4')
)

# 2. 데이터베이스 모델
class Receipt(Base):
    __tablename__ = "receipts"
    receipt_id = Column(String, primary_key=True, index=True)
    user_uuid = Column(String, index=True) # CI 대체 UUID
    type = Column(String) # 'STAY' (숙박) or 'TOUR' (소비)
    status = Column(String, default="PENDING") # PENDING, SUCCESS, FAIL, DUPLICATE
    amount = Column(Integer)
    pay_date = Column(String)
    store_name = Column(String)
    card_prefix = Column(String) # 카드 앞 4자리
    address = Column(String)
    ocr_raw = Column(JSON)
    fail_reason = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# 3. Pydantic 스키마
class PresignedUrlRequest(BaseModel):
    fileName: str
    contentType: str
    userUuid: str
    type: str # 'STAY' or 'TOUR'

class CompleteRequest(BaseModel):
    receiptId: str
    objectKey: str
    cardPrefix: str

# 4. 핵심 헬퍼 함수
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

async def call_naver_ocr(image_url: str):
    """네이버 OCR API 호출"""
    headers = {"X-OCR-SECRET": NAVER_OCR_SECRET, "Content-Type": "application/json"}
    payload = {
        "images": [{"format": "jpg", "name": "receipt", "url": image_url}],
        "requestId": str(uuid.uuid4()),
        "version": "V2",
        "timestamp": int(datetime.now().timestamp() * 1000)
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(NAVER_OCR_URL, headers=headers, json=payload)
        return response.json()

async def validate_with_gemini(store_name: str):
    """Gemini를 통한 유흥업소 여부 검증"""
    prompt = f"Is '{store_name}' a nightlife/adult entertainment venue (e.g., bar, club, karaoke for adults)? Answer only 'YES' or 'NO'."
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
    async with httpx.AsyncClient() as client:
        res = await client.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
        text = res.json()['candidates'][0]['content']['parts'][0]['text']
        return "YES" in text.upper()

# 5. API 엔드포인트
@app.post("/api/v1/receipts/presigned-url")
async def get_presigned_url(req: PresignedUrlRequest, db: Session = Depends(get_db)):
    """1단계: 업로드용 URL 발행"""
    receipt_id = str(uuid.uuid4())
    object_key = f"receipts/{receipt_id}_{req.fileName}"
    
    url = s3_client.generate_presigned_url(
        'put_object',
        Params={'Bucket': S3_BUCKET, 'Key': object_key, 'ContentType': req.contentType},
        ExpiresIn=600
    )
    
    # DB에 초기 상태 저장
    new_receipt = Receipt(receipt_id=receipt_id, user_uuid=req.userUuid, type=req.type, status="PENDING")
    db.add(new_receipt)
    db.commit()
    
    return {"uploadUrl": url, "receiptId": receipt_id, "objectKey": object_key}

@app.post("/api/v1/receipts/complete")
async def process_receipt(req: CompleteRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """2단계: OCR 분석 및 로직 검증 트리거"""
    background_tasks.add_task(analyze_receipt_task, req.receiptId, req.objectKey, req.cardPrefix)
    return {"message": "Processing started", "receiptId": req.receiptId}

async def analyze_receipt_task(receipt_id: str, object_key: str, card_prefix: str):
    """백그라운드 OCR 및 검증 로직"""
    db = SessionLocal()
    receipt = db.query(Receipt).filter(Receipt.receipt_id == receipt_id).first()
    
    try:
        image_url = s3_client.generate_presigned_url('get_object', Params={'Bucket': S3_BUCKET, 'Key': object_key}, ExpiresIn=3600)
        ocr_data = await call_naver_ocr(image_url)
        
        # OCR 데이터 파싱 (Naver Receipt 모델 기준)
        result = ocr_data['images'][0]['receipt']['result']
        store_name = result['storeInfo']['name']['text']
        total_amount = int(result['totalPrice']['price']['text'].replace(',', ''))
        pay_date = result['paymentInfo']['date']['text'] # YYYY-MM-DD
        address = result['storeInfo'].get('address', {}).get('text', '')

        # 로직 검증 시작
        fail_reason = None
        
        # 1. 2026년도 영수증 여부
        if "2026" not in pay_date:
            fail_reason = "Not a 2026 receipt"
        
        # 2. 금액 조건 확인
        if receipt.type == "STAY" and total_amount < 60000:
            fail_reason = "Stay amount under 60,000"
        elif receipt.type == "TOUR" and total_amount < 50000:
            fail_reason = "Tour amount under 50,000"

        # 3. 유흥업소 여부 (Gemini)
        if not fail_reason and await validate_with_gemini(store_name):
            fail_reason = "Inappropriate store category (Nightlife)"

        # 4. 강원도 소재지 확인 (CSV 비교 로직 예시)
        # df = pd.read_csv("gangwon_stores.csv") # 실제 파일 경로 확인 필요
        if not fail_reason and "강원" not in address:
            fail_reason = "Store not located in Gangwon"

        # 결과 업데이트
        receipt.status = "SUCCESS" if not fail_reason else "FAIL"
        receipt.store_name = store_name
        receipt.amount = total_amount
        receipt.pay_date = pay_date
        receipt.address = address
        receipt.card_prefix = card_prefix
        receipt.fail_reason = fail_reason
        receipt.ocr_raw = ocr_data
        
    except Exception as e:
        receipt.status = "ERROR"
        receipt.fail_reason = str(e)
    finally:
        db.commit()
        db.close()

@app.get("/api/v1/receipts/{receiptId}/status")
async def get_status(receiptId: str, db: Session = Depends(get_db)):
    """3단계: 분석 결과 조회"""
    receipt = db.query(Receipt).filter(Receipt.receipt_id == receiptId).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return {
        "status": receipt.status,
        "type": receipt.type,
        "amount": receipt.amount,
        "storeName": receipt.store_name,
        "failReason": receipt.fail_reason,
        "isApproved": receipt.status == "SUCCESS"
    }