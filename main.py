import os
import uuid
import httpx
import boto3
from datetime import datetime
from typing import List, Optional, Union
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import create_engine, Column, String, Integer, DateTime, JSON, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from botocore.config import Config

load_dotenv()

# 1. 인프라 설정 (환경 변수)
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[11:]
    elif DATABASE_URL.startswith("postgresql://") and "+psycopg2" not in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
S3_ENDPOINT = os.getenv("S3_ENDPOINT")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_BUCKET = os.getenv("S3_BUCKET", "gems-receipts")
NAVER_OCR_URL = os.getenv("NAVER_OCR_INVOKE_URL")
NAVER_OCR_SECRET = os.getenv("NAVER_OCR_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 2. DB 및 S3 클라이언트 초기화
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

s3_client = boto3.client(
    's3', endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY, aws_secret_access_key=S3_SECRET_KEY,
    config=Config(signature_version='s3v4')
)

# 3. 데이터베이스 모델 (자산화 분석용)
class Receipt(Base):
    __tablename__ = "receipts"
    receipt_id = Column(String, primary_key=True, index=True)
    user_uuid = Column(String, index=True)
    type = Column(String) # STAY or TOUR
    status = Column(String, default="PENDING") # PENDING, FIT, UNFIT, DUPLICATE
    amount = Column(Integer)
    pay_date = Column(String)
    store_name = Column(String)
    location = Column(String) # 시군 정보
    card_prefix = Column(String) # 카드 앞 4자리
    fail_reason = Column(String)
    ocr_raw = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# 4. Pydantic 스키마 (요구사항 반영)
class StayData(BaseModel):
    location: str
    payDate: str
    amount: int
    cardPrefix: str
    receiptImageKey: str
    isOta: bool = False
    otaStatementKey: Optional[str] = None

class TourData(BaseModel):
    storeName: str
    payDate: str
    amount: int
    cardPrefix: str
    receiptImageKeys: List[str] # 최대 3장 배열 처리

class CompleteRequest(BaseModel):
    receiptId: str
    userUuid: str
    type: str  # STAY or TOUR
    data: Union[StayData, TourData]

    @model_validator(mode="before")
    @classmethod
    def validate_data_by_type(cls, v):
        """type에 따라 data를 StayData 또는 TourData로 검증 (밸리데이션 에러 명확화)"""
        if not isinstance(v, dict) or "data" not in v or "type" not in v:
            return v
        t = v.get("type")
        inner = v.get("data")
        if not isinstance(inner, dict):
            return v
        if t == "STAY":
            v["data"] = StayData.model_validate(inner)
        elif t == "TOUR":
            v["data"] = TourData.model_validate(inner)
        return v

# 5. API 엔드포인트
app = FastAPI()

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.post("/api/v1/receipts/presigned-url")
async def get_presigned_url(fileName: str, contentType: str, userUuid: str, type: str, db: Session = Depends(get_db)):
    """1단계: 업로드 URL 발행 및 초기 레코드 생성"""
    receipt_id = str(uuid.uuid4())
    object_key = f"receipts/{receipt_id}_{fileName}"
    
    url = s3_client.generate_presigned_url(
        'put_object', Params={'Bucket': S3_BUCKET, 'Key': object_key, 'ContentType': contentType}, ExpiresIn=600
    )
    
    db.add(Receipt(receipt_id=receipt_id, user_uuid=userUuid, type=type, status="PENDING"))
    db.commit()
    return {"uploadUrl": url, "receiptId": receipt_id, "objectKey": object_key}

@app.post("/api/v1/receipts/complete")
async def submit_receipt(req: CompleteRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """3단계: 사용자 입력값 수신 및 비동기 분석 시작"""
    # DB 레코드 업데이트
    receipt = db.query(Receipt).filter(Receipt.receipt_id == req.receiptId).first()
    if not receipt: raise HTTPException(status_code=404, detail="Receipt not found")
    
    receipt.status = "PROCESSING"
    db.commit()
    
    # 백그라운드 태스크 등록 (Naver OCR + Gemini + 로직 검증)
    background_tasks.add_task(analyze_receipt_task, req)
    return {"status": "PROCESSING", "receiptId": req.receiptId}

@app.get("/api/v1/receipts/{receiptId}/status")
async def get_status(receiptId: str, db: Session = Depends(get_db)):
    """4단계: 최종 결과 조회"""
    receipt = db.query(Receipt).filter(Receipt.receipt_id == receiptId).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return {
        "status": receipt.status,
        "amount": receipt.amount,
        "failReason": receipt.fail_reason,
        "rewardAmount": 30000 if receipt.type == "STAY" and receipt.status == "FIT" else 10000 if receipt.status == "FIT" else 0
    }

# 6. 비동기 분석 로직 (Background Task)
async def analyze_receipt_task(req: CompleteRequest):
    db = SessionLocal()
    receipt = db.query(Receipt).filter(Receipt.receipt_id == req.receiptId).first()
    if not receipt:
        db.close()
        return
    try:
        # 1) Naver OCR 호출 (첫 번째 이미지 기준)
        if req.type == "STAY":
            target_key = getattr(req.data, "receiptImageKey", None)
        else:
            keys = getattr(req.data, "receiptImageKeys", None) or []
            target_key = keys[0] if keys else None
        if not target_key:
            receipt.status = "UNFIT"
            receipt.fail_reason = "BIZ_001 (No image key)"
            db.commit()
            db.close()
            return
        img_url = s3_client.generate_presigned_url('get_object', Params={'Bucket': S3_BUCKET, 'Key': target_key}, ExpiresIn=3600)
        
        async with httpx.AsyncClient() as client:
            ocr_res = await client.post(NAVER_OCR_URL, headers={"X-OCR-SECRET": NAVER_OCR_SECRET}, 
                                        json={"images": [{"format": "jpg", "name": "r", "url": img_url}], "requestId": req.receiptId, "version": "V2", "timestamp": 0})
            ocr_data = ocr_res.json()
        
        # 2) 데이터 정합성 및 비즈니스 로직 검증
        try:
            result = ocr_data["images"][0]["receipt"]["result"]
            ocr_amount = int(result["totalPrice"]["price"]["text"].replace(",", ""))
            ocr_date = result["paymentInfo"]["date"]["text"]
            store_name_text = result["storeInfo"]["name"]["text"]
        except (KeyError, IndexError, TypeError) as e:
            receipt.status = "ERROR"
            receipt.fail_reason = f"OCR response invalid: {e}"
            db.commit()
            db.close()
            return
        
        fail_reason = None
        if "2026" not in ocr_date:
            fail_reason = "BIZ_002 (Not 2026)"
        elif req.data.amount != ocr_amount:
            fail_reason = "BIZ_007 (Amount Mismatch)"
        elif req.type == "STAY" and ocr_amount < 60000:
            fail_reason = "BIZ_003 (Stay Min Amount)"
        elif req.type == "TOUR" and ocr_amount < 50000:
            fail_reason = "BIZ_003 (Tour Min Amount)"
        
        # 3) Gemini 업종 검증 (유흥주점 등)
        if not fail_reason:
            pass  # (Gemini 호출 로직 생략 - 결과가 부적합 시 fail_reason 설정)
        
        receipt.status = "FIT" if not fail_reason else "UNFIT"
        receipt.fail_reason = fail_reason
        receipt.amount = ocr_amount
        receipt.pay_date = ocr_date
        receipt.store_name = store_name_text
        receipt.ocr_raw = ocr_data
        
    except Exception as e:
        receipt.status = "ERROR"
        receipt.fail_reason = str(e)
    finally:
        db.commit()
        db.close()