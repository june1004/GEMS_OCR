import os
import re
import time
import uuid
import httpx
import boto3
from datetime import datetime
from typing import List, Optional, Union
from dotenv import load_dotenv
from sqlalchemy import text as sql_text
from fastapi import FastAPI, File, Form, HTTPException, BackgroundTasks, Depends, UploadFile
from fastapi.middleware.cors import CORSMiddleware
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
    address = Column(String)  # OCR 가맹점 주소 전체 (강원특별자치도 검증용)
    location = Column(String)  # 시군 정보 (데이터 자산화)
    card_prefix = Column(String)  # 카드 앞 4자리
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

class PresignedUrlResponse(BaseModel):
    uploadUrl: str
    receiptId: str
    objectKey: str

class CompleteResponse(BaseModel):
    status: str = "PROCESSING"
    receiptId: str

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
app = FastAPI(
    title="GEMS OCR API",
    version="1.0.0",
    description="강원 여행 인센티브 영수증 인식 API",
    servers=[{"url": "https://api.nanum.online", "description": "Production"}],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://easy.gwd.go.kr", "https://api.nanum.online"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.post("/api/v1/receipts/presigned-url", response_model=PresignedUrlResponse)
async def get_presigned_url(fileName: str, contentType: str, userUuid: str, type: str, db: Session = Depends(get_db)):
    """1단계: 고객 영수증 업로드용 Presigned URL 발급 (10분 유효) → FE가 이 URL로 PUT하여 MinIO에 저장"""
    receipt_id = str(uuid.uuid4())
    object_key = f"receipts/{receipt_id}_{fileName}"
    # 설계안: 업로드 URL 10분 유효 (PROJECT/전 단계 JSON API 설계안.md)
    url = s3_client.generate_presigned_url(
        "put_object",
        Params={"Bucket": S3_BUCKET, "Key": object_key, "ContentType": contentType},
        ExpiresIn=600,  # 10분
    )
    
    db.add(Receipt(receipt_id=receipt_id, user_uuid=userUuid, type=type, status="PENDING"))
    db.commit()
    return {"uploadUrl": url, "receiptId": receipt_id, "objectKey": object_key}


@app.post("/api/proxy/presigned-url", response_model=PresignedUrlResponse, include_in_schema=False)
async def get_presigned_url_proxy(fileName: str, contentType: str, userUuid: str, type: str, db: Session = Depends(get_db)):
    """프론트엔드 프록시 경로: /api/v1/receipts/presigned-url 와 동일"""
    return await get_presigned_url(fileName, contentType, userUuid, type, db)


@app.post("/api/v1/receipts/upload", response_model=PresignedUrlResponse)
async def upload_receipt_via_api(
    file: UploadFile = File(...),
    userUuid: str = Form(...),
    type: str = Form(...),
    db: Session = Depends(get_db),
):
    """1단계 대안: 파일을 API로 전송하면 서버가 S3에 업로드 (스토리지 CORS 미설정 시 사용)"""
    receipt_id = str(uuid.uuid4())
    name = file.filename or "image.jpg"
    object_key = f"receipts/{receipt_id}_{name}"
    content_type = file.content_type or "image/jpeg"
    body = await file.read()
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=object_key,
        Body=body,
        ContentType=content_type,
    )
    db.add(Receipt(receipt_id=receipt_id, user_uuid=userUuid, type=type, status="PENDING"))
    db.commit()
    return {"uploadUrl": "", "receiptId": receipt_id, "objectKey": object_key}


@app.post("/api/v1/receipts/complete", response_model=CompleteResponse)
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

class StatusResponse(BaseModel):
    status: Optional[str] = None
    amount: Optional[int] = None
    failReason: Optional[str] = None
    rewardAmount: int = 0
    address: Optional[str] = None  # 가맹점 주소(시군 또는 주소)
    cardPrefix: Optional[str] = None  # 카드 앞 4자리(비식별화)

@app.get(
    "/api/v1/receipts/{receiptId}/status",
    response_model=StatusResponse,
    responses={404: {"description": "Receipt not found"}},
)
async def get_status(receiptId: str, db: Session = Depends(get_db)):
    """4단계: 최종 결과 조회 (데이터 자산화: address, cardPrefix 포함)"""
    receipt = db.query(Receipt).filter(Receipt.receipt_id == receiptId).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    address = (receipt.address or receipt.location or receipt.store_name or "").strip() or None
    return StatusResponse(
        status=receipt.status,
        amount=receipt.amount,
        failReason=receipt.fail_reason,
        rewardAmount=30000 if receipt.type == "STAY" and receipt.status == "FIT" else 10000 if receipt.status == "FIT" else 0,
        address=address,
        cardPrefix=receipt.card_prefix,
    )


@app.get(
    "/api/proxy/status/{receiptId}",
    response_model=StatusResponse,
    responses={404: {"description": "Receipt not found"}},
    include_in_schema=False,
)
async def get_status_proxy(receiptId: str, db: Session = Depends(get_db)):
    """프론트엔드 프록시 경로: /api/v1/receipts/{id}/status 와 동일 응답"""
    return await get_status(receiptId, db)


# 6. Naver 영수증 OCR 연동 (CLOVA Document OCR > 영수증)
# 참고: https://api.ncloud-docs.com/docs/ai-application-service-ocr-ocrdocumentocr-receipt
# - 저장된 이미지(1단계 Presigned PUT → MinIO)를 Get Presigned URL로 Naver에 전달
def _get_presigned_get_url(object_key: str, expires: int = 60) -> str:
    """Naver OCR이 MinIO에 저장된 이미지에 접근할 수 있도록 Get Presigned URL (1분)"""
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": object_key},
        ExpiresIn=expires,
    )


async def _call_naver_ocr(image_url: str, receipt_id: str) -> dict:
    """CLOVA OCR 영수증 API 호출 (MinIO 이미지 Get Presigned URL 전달). X-OCR-SECRET, V2, timestamp 필수."""
    headers = {
        "X-OCR-SECRET": NAVER_OCR_SECRET,
        "Content-Type": "application/json",
    }
    payload = {
        "images": [{"format": "jpg", "name": "receipt_sample", "url": image_url}],
        "requestId": receipt_id,
        "version": "V2",
        "timestamp": int(time.time() * 1000),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(NAVER_OCR_URL, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


def _parse_ocr_result(ocr_data: dict) -> tuple[Optional[int], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Naver OCR JSON 파싱. 반환: (amount, pay_date, store_name, address, location_시군).
    실패 시 (None, None, None, None, None).
    """
    try:
        images = ocr_data.get("images") or []
        if not images:
            return (None, None, None, None, None)
        receipt = images[0].get("receipt") or {}
        result = receipt.get("result")
        if not result:
            return (None, None, None, None, None)
        # 결제 금액
        price_text = (result.get("totalPrice") or {}).get("price") or {}
        amount_str = (price_text.get("text") or "0").replace(",", "").strip()
        amount = int(amount_str) if amount_str.isdigit() else None
        # 결제 날짜
        payment_info = result.get("paymentInfo") or {}
        date_obj = payment_info.get("date") or {}
        pay_date = (date_obj.get("text") or "").strip()
        # 상호명
        store_info = result.get("storeInfo") or {}
        store_name = (store_info.get("name") or {}).get("text") or ""
        store_name = store_name.strip()
        # 주소 (강원특별자치도 검증용)
        addr_obj = store_info.get("address") or {}
        address = (addr_obj.get("text") or "").strip()
        # 시군: 주소에서 두 번째 단어 (춘천시 등)
        location = ""
        if address:
            parts = address.split()
            location = parts[1] if len(parts) >= 2 else ""
        return (amount, pay_date, store_name, address, location)
    except (KeyError, IndexError, TypeError, ValueError):
        return (None, None, None, None, None)


def _check_duplicate_receipt(db: Session, store_name: str, pay_date: str, amount: int, card_prefix: str) -> bool:
    """동일 상호명+결제날짜+금액+카드앞4자리 존재 시 True (BIZ_001)"""
    q = db.query(Receipt).filter(
        Receipt.store_name == store_name,
        Receipt.pay_date == pay_date,
        Receipt.amount == amount,
        Receipt.card_prefix == card_prefix,
        Receipt.status == "FIT",
    )
    return q.first() is not None


def _check_store_in_master(db: Session, store_name: str, city_county: str) -> bool:
    """master_stores에 상호+시군 존재 여부 (BIZ_004/OCR_003)"""
    try:
        if city_county:
            r = db.execute(
                sql_text(
                    "SELECT 1 FROM master_stores WHERE store_name = :sn AND (city_county = :cc OR road_address LIKE :addr)"
                ),
                {"sn": store_name, "cc": city_county, "addr": f"%{city_county}%"},
            )
        else:
            r = db.execute(sql_text("SELECT 1 FROM master_stores WHERE store_name = :sn"), {"sn": store_name})
        return r.scalar() is not None
    except Exception:
        return False


# 2026년 날짜 여부 (숫자 2026 포함)
def _is_2026_date(date_text: str) -> bool:
    return bool(re.search(r"2026", date_text or ""))


async def analyze_receipt_task(req: CompleteRequest):
    """영수증 OCR 분석 및 PRD 검증 → DB 자산화."""
    db = SessionLocal()
    receipt = db.query(Receipt).filter(Receipt.receipt_id == req.receiptId).first()
    if not receipt:
        db.close()
        return
    try:
        # 1) 이미지 키 → Get Presigned URL (1분)
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

        image_url = _get_presigned_get_url(target_key, expires=60)

        # 2) Naver OCR 호출
        try:
            ocr_data = await _call_naver_ocr(image_url, req.receiptId)
        except httpx.HTTPStatusError as e:
            receipt.status = "ERROR"
            receipt.fail_reason = f"OCR_001 (OCR API error: {e.response.status_code})"
            db.commit()
            db.close()
            return
        except Exception as e:
            receipt.status = "ERROR"
            receipt.fail_reason = f"OCR_001 (OCR request failed: {e})"
            db.commit()
            db.close()
            return

        amount, pay_date, store_name, address, location = _parse_ocr_result(ocr_data)
        if amount is None and not store_name:
            receipt.status = "UNFIT"
            receipt.fail_reason = "OCR_001 (영수증 판독 불가 - 다시 촬영 권장)"
            receipt.ocr_raw = ocr_data
            db.commit()
            db.close()
            return

        receipt.amount = amount
        receipt.pay_date = pay_date or ""
        receipt.store_name = store_name or ""
        receipt.address = address or ""
        receipt.location = location or getattr(req.data, "location", None) or ""
        receipt.card_prefix = req.data.cardPrefix
        receipt.ocr_raw = ocr_data

        # 3) PRD 검증
        fail_reason = None
        if req.data.amount != (amount or 0):
            fail_reason = "BIZ_007 (Amount Mismatch)"
        elif not _is_2026_date(pay_date or ""):
            fail_reason = "BIZ_002 (Not 2026)"
        elif req.type == "STAY" and (amount or 0) < 60000:
            fail_reason = "BIZ_003 (Stay Min Amount)"
        elif req.type == "TOUR" and (amount or 0) < 50000:
            fail_reason = "BIZ_003 (Tour Min Amount)"
        elif address and "강원특별자치도" not in address:
            fail_reason = "BIZ_004 (Not Gangwon address)"
        elif not _check_store_in_master(db, store_name or "", location or ""):
            fail_reason = "OCR_003 (Store not in master_stores)"
        elif _check_duplicate_receipt(db, store_name or "", pay_date or "", amount or 0, req.data.cardPrefix):
            receipt.status = "DUPLICATE"
            receipt.fail_reason = "BIZ_001 (Duplicate receipt)"
            receipt.amount = amount
            db.commit()
            db.close()
            return

        receipt.status = "FIT" if not fail_reason else "UNFIT"
        receipt.fail_reason = fail_reason
        receipt.amount = amount

    except Exception as e:
        receipt.status = "ERROR"
        receipt.fail_reason = str(e)
    finally:
        db.commit()
        db.close()