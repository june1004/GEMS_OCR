import io
import os
import re
import time
import uuid
import json
import asyncio
import logging
from enum import Enum
import httpx
import boto3
from PIL import Image, ImageOps, ImageEnhance
from botocore.exceptions import ClientError, BotoCoreError
from datetime import datetime
from typing import Any, Dict, List, Optional, Union, Tuple
from dotenv import load_dotenv
from dateutil import parser as dateutil_parser
from sqlalchemy import text as sql_text

from processor import validate_and_match, validate_campaign_rules, match_store_in_master
from fastapi import FastAPI, File, Form, HTTPException, BackgroundTasks, Depends, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator, UUID4, ConfigDict
from sqlalchemy import create_engine, Column, String, Integer, DateTime, JSON, Boolean, ARRAY, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.dialects.postgresql import JSONB
from botocore.config import Config

load_dotenv()

# 로거 설정 (에러 스택 트레이스 확인용)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

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

# 3. 데이터베이스 모델 (1:N 상속형 자산화 구조)
class Submission(Base):
    __tablename__ = "submissions"
    submission_id = Column(String, primary_key=True, index=True)
    user_uuid = Column(String, index=True, nullable=False)
    project_type = Column(String, nullable=False)  # STAY | TOUR
    campaign_id = Column(Integer, default=1)
    status = Column(String, default="PENDING")  # PENDING | PROCESSING | FIT | UNFIT | ERROR
    total_amount = Column(Integer)
    global_fail_reason = Column(String)
    audit_trail = Column(String)
    fail_reason = Column(String)
    audit_log = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    items = relationship("ReceiptItem", back_populates="submission", cascade="all, delete-orphan")


class ReceiptItem(Base):
    __tablename__ = "receipt_items"
    item_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    submission_id = Column(String, ForeignKey("submissions.submission_id"), index=True, nullable=False)
    seq_no = Column(Integer, nullable=False, default=1)  # 업로드 순번
    doc_type = Column(String, nullable=False, default="RECEIPT")
    image_key = Column(String(500), nullable=False)
    # 개별 OCR 자산 필드
    store_name = Column(String)
    biz_num = Column(String)
    pay_date = Column(String)
    amount = Column(Integer)
    address = Column(String)
    location = Column(String)
    card_num = Column(String, default="0000")
    status = Column(String, default="PENDING")  # PENDING | FIT | UNFIT | ERROR
    error_code = Column(String)
    error_message = Column(String)
    confidence_score = Column(Integer)  # 0~100 정수
    ocr_raw = Column(JSONB)
    parsed = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)
    submission = relationship("Submission", back_populates="items")


class UnregisteredStore(Base):
    __tablename__ = "unregistered_stores"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    store_name = Column(String(255))
    biz_num = Column(String(64), index=True)
    address = Column(String(500))
    tel = Column(String(64))
    status = Column(String(32), default="TEMP_VALID")  # TEMP_VALID | APPROVED | REJECTED
    source_submission_id = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# 4. Pydantic 스키마 (1:N + 자산화 지침 반영)
class ProjectType(str, Enum):
    STAY = "STAY"
    TOUR = "TOUR"


class ProcessStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    VERIFYING = "VERIFYING"
    FIT = "FIT"
    UNFIT = "UNFIT"
    ERROR = "ERROR"
    PENDING_NEW = "PENDING_NEW"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    UNFIT_CATEGORY = "UNFIT_CATEGORY"
    UNFIT_REGION = "UNFIT_REGION"
    UNFIT_DATE = "UNFIT_DATE"
    UNFIT_DUPLICATE = "UNFIT_DUPLICATE"
    ERROR_OCR = "ERROR_OCR"


class ErrorCode(str, Enum):
    BIZ_001 = "BIZ_001"
    BIZ_002 = "BIZ_002"
    BIZ_003 = "BIZ_003"
    BIZ_004 = "BIZ_004"
    BIZ_005 = "BIZ_005"
    BIZ_006 = "BIZ_006"
    BIZ_007 = "BIZ_007"
    BIZ_008 = "BIZ_008"
    BIZ_010 = "BIZ_010"
    BIZ_011 = "BIZ_011"
    OCR_001 = "OCR_001"
    OCR_002 = "OCR_002"
    OCR_003 = "OCR_003"
    PENDING_NEW = "PENDING_NEW"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    UNFIT_CATEGORY = "UNFIT_CATEGORY"
    UNFIT_REGION = "UNFIT_REGION"
    UNFIT_DATE = "UNFIT_DATE"
    UNFIT_DUPLICATE = "UNFIT_DUPLICATE"
    ERROR_OCR = "ERROR_OCR"


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


class ReceiptMetadata(BaseModel):
    imageKey: str
    docType: str  # RECEIPT | OTA_INVOICE

class PresignedUrlResponse(BaseModel):
    uploadUrl: str
    receiptId: str
    objectKey: str

class CompleteResponse(BaseModel):
    status: ProcessStatus = ProcessStatus.PROCESSING
    receiptId: str

class CompleteRequest(BaseModel):
    receiptId: str
    userUuid: str
    type: str  # STAY or TOUR
    campaignId: int = 1  # 캠페인 필터(지역·기간) 적용, 기본 1
    data: Optional[Union[StayData, TourData]] = None
    documents: Optional[List[ReceiptMetadata]] = None

    @model_validator(mode="before")
    @classmethod
    def validate_data_by_type(cls, v):
        """type에 따라 data를 StayData 또는 TourData로 검증 (밸리데이션 에러 명확화)"""
        if not isinstance(v, dict) or "type" not in v:
            return v
        t = v.get("type")
        docs = v.get("documents")
        data = v.get("data")

        if t not in ("STAY", "TOUR"):
            raise ValueError("type must be STAY or TOUR")

        if docs is not None:
            if not isinstance(docs, list) or len(docs) == 0:
                raise ValueError("documents must be a non-empty array")
            normalized_docs: List[ReceiptMetadata] = []
            for d in docs:
                md = ReceiptMetadata.model_validate(d)
                if not (md.imageKey or "").strip():
                    raise ValueError("document imageKey cannot be empty")
                if md.docType not in ("RECEIPT", "OTA_INVOICE"):
                    raise ValueError("docType must be RECEIPT or OTA_INVOICE")
                normalized_docs.append(md)
            v["documents"] = normalized_docs

            if t == "STAY":
                receipt_cnt = len([d for d in normalized_docs if d.docType == "RECEIPT"])
                ota_cnt = len([d for d in normalized_docs if d.docType == "OTA_INVOICE"])
                if receipt_cnt < 1:
                    raise ValueError("STAY requires at least one RECEIPT document")
                if receipt_cnt > 1 or ota_cnt > 1:
                    raise ValueError("STAY supports RECEIPT(1) + OTA_INVOICE(0~1)")
            else:
                if len(normalized_docs) < 1 or len(normalized_docs) > 3:
                    raise ValueError("TOUR supports 1 to 3 documents")
                if any(d.docType != "RECEIPT" for d in normalized_docs):
                    raise ValueError("TOUR supports RECEIPT documents only")

        if data is not None and isinstance(data, dict):
            if t == "STAY":
                v["data"] = StayData.model_validate(data)
            elif t == "TOUR":
                v["data"] = TourData.model_validate(data)

        if v.get("documents") is None and v.get("data") is None:
            raise ValueError("Either documents or legacy data is required")

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


def _check_s3_connection() -> Tuple[bool, Optional[str]]:
    """S3(MinIO) 연결 및 버킷 접근 가능 여부 확인. 반환: (성공 여부, 실패 시 메시지)."""
    try:
        s3_client.head_bucket(Bucket=S3_BUCKET)
        return True, None
    except ClientError as e:
        err = e.response.get("Error", {})
        code = err.get("Code", "")
        msg = err.get("Message", str(e))
        logger.error("S3 ClientError: %s - %s", code, msg, exc_info=True)
        return False, f"S3 오류({code}): {msg}"
    except BotoCoreError as e:
        logger.error("S3 BotoCoreError: %s", e, exc_info=True)
        return False, f"S3 연결 오류: {str(e)}"
    except Exception as e:
        logger.error("S3 unexpected error: %s", e, exc_info=True)
        return False, f"S3 오류: {str(e)}"


def _check_db_connection() -> Tuple[bool, Optional[str]]:
    """DB 연결 및 핵심 테이블 존재 여부 확인. 반환: (성공 여부, 실패 시 메시지)."""
    try:
        db = SessionLocal()
        try:
            db.execute(sql_text("SELECT 1"))
            db.execute(sql_text("SELECT 1 FROM submissions LIMIT 1"))
            db.execute(sql_text("SELECT 1 FROM receipt_items LIMIT 1"))
            db.execute(sql_text("SELECT 1 FROM unregistered_stores LIMIT 1"))
            return True, None
        finally:
            db.close()
    except Exception as e:
        logger.error("DB connection error: %s", e, exc_info=True)
        return False, f"DB 오류: {str(e)}"


@app.get("/api/health", summary="헬스 체크 (S3·DB 연결 확인)")
async def health_check():
    """S3 버킷 접근 및 DB 연결·테이블 존재 여부를 확인합니다. 배포/프록시에서 사용."""
    s3_ok, s3_msg = _check_s3_connection()
    db_ok, db_msg = _check_db_connection()
    ok = s3_ok and db_ok
    detail = {}
    if not s3_ok:
        detail["s3"] = s3_msg
    if not db_ok:
        detail["db"] = db_msg
    if not ok:
        raise HTTPException(status_code=503, detail=detail)
    return {"status": "ok", "s3": "ok", "db": "ok"}


@app.post("/api/v1/receipts/presigned-url", response_model=PresignedUrlResponse)
async def get_presigned_url(
    fileName: str,
    contentType: str,
    userUuid: str,
    type: str,
    receiptId: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    1단계: 고객 영수증 업로드용 Presigned URL 발급 (10분 유효).
    - receiptId를 전달하면 동일 신청(합산형)으로 이미지를 계속 추가할 수 있음.
    - receiptId 미전달 시 새 신청을 생성.
    """
    if type not in ("STAY", "TOUR"):
        raise HTTPException(status_code=400, detail="type must be STAY or TOUR")

    receipt_id = receiptId or str(uuid.uuid4())
    object_key = f"receipts/{receipt_id}_{uuid.uuid4().hex[:8]}_{fileName}"

    try:
        url = s3_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": S3_BUCKET, "Key": object_key, "ContentType": contentType},
            ExpiresIn=600,
        )
    except ClientError as e:
        err = e.response.get("Error", {})
        code = err.get("Code", "")
        msg = err.get("Message", str(e))
        logger.error("S3 Presigned URL ClientError: %s - %s", code, msg, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"S3 오류(Presigned URL): {code} - {msg}",
        )
    except (BotoCoreError, Exception) as e:
        logger.error("S3 Presigned URL unexpected error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Presigned URL 생성 실패: {str(e)}",
        )

    try:
        existing = db.query(Submission).filter(Submission.submission_id == receipt_id).first()
        if existing:
            if existing.user_uuid != userUuid:
                raise HTTPException(status_code=403, detail="receiptId owner mismatch")
            existing.project_type = type
        else:
            db.add(
                Submission(
                    submission_id=receipt_id,
                    user_uuid=userUuid,
                    project_type=type,
                    campaign_id=1,
                    status="PENDING",
                    total_amount=0,
                )
            )
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("DB error in presigned-url: %s", e, exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB 오류: {str(e)}")

    return {"uploadUrl": url, "receiptId": receipt_id, "objectKey": object_key}


@app.post("/api/proxy/presigned-url", response_model=PresignedUrlResponse, include_in_schema=False)
async def get_presigned_url_proxy(
    fileName: str,
    contentType: str,
    userUuid: str,
    type: str,
    receiptId: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """프론트엔드 프록시 경로: /api/v1/receipts/presigned-url 와 동일"""
    return await get_presigned_url(fileName, contentType, userUuid, type, receiptId, db)


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
    try:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=object_key,
            Body=body,
            ContentType=content_type,
        )
    except ClientError as e:
        err = e.response.get("Error", {})
        logger.error("S3 put_object ClientError: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"S3 업로드 오류: {err.get('Message', str(e))}")
    except (BotoCoreError, Exception) as e:
        logger.error("S3 put_object error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"S3 업로드 실패: {str(e)}")
    try:
        db.add(
            Submission(
                submission_id=receipt_id,
                user_uuid=userUuid,
                project_type=type,
                campaign_id=1,
                status="PENDING",
                total_amount=0,
            )
        )
        db.commit()
    except Exception as e:
        logger.error("DB error in upload: %s", e, exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB 오류: {str(e)}")
    return {"uploadUrl": "", "receiptId": receipt_id, "objectKey": object_key}


@app.post("/api/v1/receipts/complete", response_model=CompleteResponse)
async def submit_receipt(req: CompleteRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """3단계: 사용자 입력값 수신 및 비동기 분석 시작 (합산형 documents 지원)"""
    submission = db.query(Submission).filter(Submission.submission_id == req.receiptId).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    if submission.user_uuid != req.userUuid:
        raise HTTPException(status_code=403, detail="receiptId owner mismatch")

    if submission.status in ("FIT", "UNFIT", "ERROR"):
        raise HTTPException(status_code=409, detail="Submission already completed")

    if submission.status in ("PROCESSING", "VERIFYING"):
        return {"status": submission.status, "receiptId": req.receiptId}

    submission.campaign_id = req.campaignId
    submission.status = "PROCESSING"
    db.commit()

    background_tasks.add_task(analyze_receipt_task, req)
    return {"status": "PROCESSING", "receiptId": req.receiptId}

class ExtractedData(BaseModel):
    store_name: Optional[str] = Field(None, description="상호명")
    amount: int = Field(0, description="인식된 금액")
    pay_date: Optional[str] = Field(None, description="결제일자")
    address: Optional[str] = Field(None, description="상점 주소")
    card_num: str = Field("0000", description="카드번호 앞 4자리 (현금/미인식 시 0000)")


class ReceiptItemSchema(BaseModel):
    item_id: str
    status: ProcessStatus
    error_code: Optional[ErrorCode] = None
    error_message: Optional[str] = None
    extracted_data: Optional[ExtractedData] = None
    image_url: str = Field(..., description="MinIO object key 또는 접근 URL")
    ocr_raw: Optional[Dict[str, Any]] = Field(None, description="원본 OCR JSON (자산화)")


class SubmissionStatusResponse(BaseModel):
    submission_id: UUID4
    project_type: ProjectType
    overall_status: ProcessStatus
    total_amount: int = Field(0, description="FIT 상태인 영수증들의 합산 금액")
    global_fail_reason: Optional[str] = Field(None, description="사업 기준 미달 사유")
    items: List[ReceiptItemSchema] = Field(default_factory=list, description="하위 영수증 목록")
    audit_trail: str = Field("", description="시스템 판정 근거 요약")

    model_config = ConfigDict(from_attributes=True)


class StatusResponse(SubmissionStatusResponse):
    # 하위호환 필드
    status: Optional[ProcessStatus] = None
    amount: Optional[int] = None
    failReason: Optional[str] = None
    rewardAmount: int = 0
    address: Optional[str] = None
    cardPrefix: Optional[str] = None

def _sanitize_receipt_id(raw: str) -> str:
    """FE/프록시에서 잘못 붙은 문자가 있을 수 있음 (예: 'uuid HTTP/1.1\" 404...'). UUID만 추출."""
    if not raw:
        return ""
    s = raw.strip()
    match = re.match(r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", s)
    return match.group(1) if match else s.split()[0] if s.split() else s


@app.get(
    "/api/v1/receipts/{receiptId}/status",
    response_model=StatusResponse,
    responses={404: {"description": "Receipt not found"}},
)
async def get_status(receiptId: str, db: Session = Depends(get_db)):
    """4단계: 최종 결과 조회 (데이터 자산화: address, cardPrefix 포함)"""
    receipt_id = _sanitize_receipt_id(receiptId)
    submission = db.query(Submission).filter(Submission.submission_id == receipt_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    item_rows = (
        db.query(ReceiptItem)
        .filter(ReceiptItem.submission_id == receipt_id)
        .order_by(ReceiptItem.seq_no.asc())
        .all()
    )
    first_item = item_rows[0] if item_rows else None
    address = None
    card_prefix = None
    if first_item:
        address = (first_item.address or first_item.location or first_item.store_name or "").strip() or None
        card_prefix = first_item.card_num or None
    item_details: List[ReceiptItemSchema] = []
    for it in item_rows:
        extracted = None
        if it.status != "ERROR":
            extracted = ExtractedData(
                store_name=it.store_name,
                amount=it.amount or 0,
                pay_date=it.pay_date,
                address=it.address,
                card_num=it.card_num or "0000",
            )
        item_details.append(
            ReceiptItemSchema(
                item_id=it.item_id,
                status=it.status or "PENDING",
                error_code=_normalize_error_code(it.error_code),
                error_message=it.error_message,
                extracted_data=extracted,
                image_url=it.image_key,
                ocr_raw=it.ocr_raw,
            )
        )
    return StatusResponse(
        submission_id=submission.submission_id,
        project_type=submission.project_type,
        overall_status=submission.status,
        total_amount=submission.total_amount,
        global_fail_reason=submission.global_fail_reason or submission.fail_reason,
        items=item_details,
        audit_trail=(submission.audit_trail or submission.audit_log or ""),
        status=submission.status,
        amount=submission.total_amount,
        failReason=submission.fail_reason,
        rewardAmount=30000 if submission.project_type == "STAY" and submission.status == "FIT" else 10000 if submission.status == "FIT" else 0,
        address=address,
        cardPrefix=card_prefix,
    )


@app.get(
    "/api/v1/receipts/status/{receiptId}",
    response_model=StatusResponse,
    responses={404: {"description": "Receipt not found"}},
    include_in_schema=False,
)
async def get_status_alt(receiptId: str, db: Session = Depends(get_db)):
    """경로 별칭: FE가 /api/v1/receipts/status/{id} 로 호출할 때"""
    return await get_status(receiptId, db)


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
# - 권장: multipart(바이너리) + 리사이징/압축으로 전송량·비용 절감
MAX_OCR_DIMENSION = 2000
JPEG_QUALITY = 80


def _get_image_bytes_from_s3(object_key: str) -> Tuple[bytes, str]:
    """MinIO에서 이미지 바이너리 직접 읽기. 반환: (bytes, content_type)."""
    resp = s3_client.get_object(Bucket=S3_BUCKET, Key=object_key)
    body = resp["Body"].read()
    content_type = (resp.get("ContentType") or "image/jpeg").lower()
    return body, content_type


def _resize_and_compress_for_ocr(
    image_bytes: bytes, content_type: str
) -> Tuple[bytes, str]:
    """
    리사이징(가로/세로 최대 2000px) + JPEG 압축(quality 80). 전송량·OCR 비용 절감.
    실패 시 원본 반환. 반환: (bytes, content_type).
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # EXIF 방향 보정 (촬영 방향 뒤집힘 방지)
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        # 가벼운 대비/선명도 보정으로 OCR 안정성 향상
        img = ImageOps.autocontrast(img, cutoff=1)
        img = ImageEnhance.Sharpness(img).enhance(1.2)
        w, h = img.size
        if w > MAX_OCR_DIMENSION or h > MAX_OCR_DIMENSION:
            ratio = min(MAX_OCR_DIMENSION / w, MAX_OCR_DIMENSION / h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return image_bytes, content_type


def _image_format_from_content_type(content_type: str) -> str:
    """Content-Type → 네이버 OCR format (jpg|png)."""
    if "png" in content_type:
        return "png"
    return "jpg"


def _normalize_and_validate_2026_date(date_text: str) -> Tuple[bool, Optional[str]]:
    """
    OCR 날짜 정규화 후 2026년 유효성 검사.
    Step1: 구분자(., /, 공백)를 '-'로 치환
    Step2: 2026 또는 26으로 시작하는지 확인
    Step3: dateutil.parser로 파싱 후 유효한 날짜인지 검증
    반환: (2026년 유효 여부, 정규화된 날짜 문자열 또는 None)
    """
    if not date_text or not isinstance(date_text, str):
        return False, None
    s = date_text.strip()
    s = re.sub(r"[/.\s]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("- ")
    if not re.match(r"^(2026|26)", s):
        return False, None
    if s.startswith("26"):
        s = "20" + s
    try:
        parsed = dateutil_parser.parse(s)
        if parsed.year != 2026:
            return False, None
        normalized = parsed.strftime("%Y-%m-%d")
        return True, normalized
    except (ValueError, TypeError):
        return False, None


async def _call_naver_ocr_binary(
    image_binary: bytes, receipt_id: str, image_format: str = "jpg"
) -> dict:
    """
    CLOVA OCR 영수증 API — multipart/form-data(바이너리) 전송.
    Base64 대비 용량·메모리 효율적이며 네이버 권장 방식.
    """
    message = {
        "version": "V2",
        "requestId": receipt_id,
        "timestamp": int(time.time() * 1000),
        "images": [{"format": image_format, "name": "receipt"}],
    }
    mime = "image/jpeg" if image_format == "jpg" else "image/png"
    files = {
        "file": ("receipt.jpg" if image_format == "jpg" else "receipt.png", image_binary, mime),
        "message": (None, json.dumps(message), "application/json"),
    }
    headers = {"X-OCR-SECRET": NAVER_OCR_SECRET}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(NAVER_OCR_URL, headers=headers, files=files)
        response.raise_for_status()
        return response.json()


async def _call_naver_ocr_with_retry(
    image_binary: bytes, receipt_id: str, image_format: str = "jpg", retries: int = 2
) -> dict:
    """
    네이버 OCR 호출 재시도 래퍼.
    - 네트워크/일시적 API 오류 시 최대 retries+1회 시도
    """
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return await _call_naver_ocr_binary(image_binary, receipt_id, image_format)
        except Exception as e:
            last_exc = e
            logger.warning(
                "Naver OCR call failed (attempt %s/%s): %s",
                attempt + 1,
                retries + 1,
                e,
            )
            if attempt < retries:
                await asyncio.sleep(0.4 * (attempt + 1))
    raise last_exc if last_exc else RuntimeError("Naver OCR failed")


def _parse_ocr_result(ocr_data: dict) -> tuple[Optional[int], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Naver OCR JSON 파싱. 반환: (amount, pay_date, store_name, address, location_시군).
    - 주소: storeInfo.address.text 없으면 storeInfo.addresses[0].text 사용 (CLOVA 응답 형식 대응).
    - 금액: totalPrice가 비정상적으로 작거나 없으면 subTotal 부가세로 추정 (VAT 10% → 총액 ≈ 세액×10).
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
        raw_price = (price_text.get("text") or "0").strip()
        amount_str = re.sub(r"[^0-9]", "", raw_price)
        amount = int(amount_str) if amount_str else None
        # 금액이 없거나 비정상적으로 작을 때(< 1,000원) subTotal 부가세로 추정
        if amount is None or amount < 1000:
            sub_total = result.get("subTotal") or []
            if isinstance(sub_total, list) and len(sub_total) > 0:
                first = sub_total[0]
                tax_prices = (first.get("taxPrice") or []) if isinstance(first, dict) else []
                if tax_prices and isinstance(tax_prices[0], dict):
                    tax_text = (tax_prices[0].get("text") or "").strip()
                    tax_num = re.sub(r"[^0-9]", "", tax_text)
                    if tax_num:
                        tax_val = int(tax_num)
                        if tax_val >= 100:
                            amount = tax_val * 10  # 부가세 10% 기준 총액 추정
        # 결제 날짜
        payment_info = result.get("paymentInfo") or {}
        date_obj = payment_info.get("date") or {}
        pay_date = (date_obj.get("text") or "").strip()
        # 상호명
        store_info = result.get("storeInfo") or {}
        store_name = (store_info.get("name") or {}).get("text") or ""
        store_name = store_name.strip()
        # 주소: address 단일 객체 또는 addresses 배열 (CLOVA 형식)
        addr_obj = store_info.get("address") or {}
        address = (addr_obj.get("text") or "").strip()
        if not address:
            addrs = store_info.get("addresses") or []
            if isinstance(addrs, list) and len(addrs) > 0:
                first_addr = addrs[0] if isinstance(addrs[0], dict) else {}
                address = (first_addr.get("text") or "").strip()
        # 시군: 주소에서 두 번째 단어 (속초시, 춘천시 등)
        location = ""
        if address:
            parts = address.split()
            location = parts[1] if len(parts) >= 2 else ""
        return (amount, pay_date, store_name, address, location)
    except (KeyError, IndexError, TypeError, ValueError):
        return (None, None, None, None, None)


def _extract_business_num(ocr_data: dict) -> Optional[str]:
    """
    OCR 결과에서 사업자등록번호(bizNum) 텍스트 추출. 실패 시 None.
    """
    try:
        images = ocr_data.get("images") or []
        if not images:
            return None
        receipt = images[0].get("receipt") or {}
        result = receipt.get("result") or {}
        store_info = result.get("storeInfo") or {}
        biz_obj = store_info.get("bizNum") or {}
        biz = (biz_obj.get("text") or "").strip()
        return biz or None
    except (KeyError, TypeError, ValueError):
        return None


def _normalize_card_num(raw: Optional[str]) -> str:
    """
    카드번호 정규화:
    - 숫자 4자리 이상이면 마지막 4자리 저장
    - 비어 있거나 은행명/문자열 등 카드번호가 아니면 '0000'
    """
    text = (raw or "").strip()
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) >= 4:
        return digits[-4:]
    return "0000"


def _extract_card_num(ocr_data: dict) -> str:
    """OCR 결과에서 카드번호(last4)를 추출. 없거나 비정상이면 0000."""
    try:
        images = ocr_data.get("images") or []
        if not images:
            return "0000"
        result = (images[0].get("receipt") or {}).get("result") or {}
        card_info = (result.get("paymentInfo") or {}).get("cardInfo") or {}
        card_num_obj = card_info.get("number") or {}
        return _normalize_card_num(card_num_obj.get("text"))
    except Exception:
        return "0000"


def _extract_confidence_score(ocr_data: dict) -> Optional[int]:
    """영수증별 신뢰도 스냅샷(0~100): totalPrice.price confidence 우선."""
    try:
        images = ocr_data.get("images") or []
        if not images:
            return None
        result = (images[0].get("receipt") or {}).get("result") or {}
        price = (result.get("totalPrice") or {}).get("price") or {}
        conf = price.get("confidenceScore")
        if isinstance(conf, (int, float)):
            return int(round(float(conf) * 100))
        return None
    except Exception:
        return None


def _check_duplicate_receipt_item(
    db: Session,
    submission_id: str,
    biz_num: Optional[str],
    pay_date: str,
    amount: int,
    card_num: str,
) -> bool:
    """
    item 단위 중복 체크:
    biz_num + pay_date + amount + card_num(0000 포함) 조합이 다른 FIT 신청에 존재하면 True.
    """
    if not biz_num:
        return False
    q = (
        db.query(ReceiptItem)
        .join(Submission, Submission.submission_id == ReceiptItem.submission_id)
        .filter(ReceiptItem.biz_num == biz_num)
        .filter(ReceiptItem.pay_date == pay_date)
        .filter(ReceiptItem.amount == amount)
        .filter(ReceiptItem.card_num == _normalize_card_num(card_num))
        .filter(ReceiptItem.submission_id != submission_id)
        .filter(Submission.status == "FIT")
    )
    return q.first() is not None


# 유흥업소 등 부적격 업태 키워드 (BIZ_008)
FORBIDDEN_BUSINESS_KEYWORDS = ("단란주점", "유흥주점", "유흥주점영업", "무도장", "사교춤장")
OCR_CONFIDENCE_THRESHOLD = 90  # >= 90%면 OCR 우선 신뢰
AMOUNT_MISMATCH_RATIO_THRESHOLD = 0.10  # 10% 이상 차이 시 수동 검증 보류


def _ocr_contains_forbidden_business(ocr_data: dict) -> bool:
    """OCR 결과 전체 텍스트에서 부적격 업태 키워드 포함 여부. 포함 시 True."""
    try:
        text = json.dumps(ocr_data, ensure_ascii=False)
        return any(kw in text for kw in FORBIDDEN_BUSINESS_KEYWORDS)
    except Exception:
        return False


def _extract_store_tel(ocr_data: dict) -> Optional[str]:
    """OCR 결과에서 가맹점 전화번호 추출."""
    try:
        images = ocr_data.get("images") or []
        if not images:
            return None
        result = (images[0].get("receipt") or {}).get("result") or {}
        store_info = result.get("storeInfo") or {}
        tel_list = store_info.get("tel") or []
        if isinstance(tel_list, list) and tel_list:
            tel_text = (tel_list[0].get("text") or "").strip()
            return tel_text or None
    except Exception:
        return None
    return None


def _is_amount_mismatch(user_amount: Optional[int], ocr_amount: Optional[int]) -> bool:
    """사용자 입력 금액과 OCR 금액 차이가 10% 이상인지 판정."""
    if user_amount is None or ocr_amount is None:
        return False
    base = max(user_amount, 1)
    ratio = abs(ocr_amount - user_amount) / base
    return ratio >= AMOUNT_MISMATCH_RATIO_THRESHOLD


def _register_new_candidate_store(db: Session, submission_id: str, parsed: Dict[str, Any], ocr_raw: Optional[Dict[str, Any]]) -> None:
    """
    마스터 미등록 상점을 임시 등록(TEMP_VALID).
    biz_num+address+tel 조합 우선으로 중복 등록 방지.
    """
    biz_num = (parsed.get("businessNum") or "").strip() or None
    address = (parsed.get("address") or "").strip() or None
    tel = _extract_store_tel(ocr_raw or {}) if ocr_raw else None
    store_name = (parsed.get("storeName") or "").strip() or None

    q = db.query(UnregisteredStore).filter(UnregisteredStore.status == "TEMP_VALID")
    if biz_num:
        q = q.filter(UnregisteredStore.biz_num == biz_num)
    if address:
        q = q.filter(UnregisteredStore.address == address)
    if tel:
        q = q.filter(UnregisteredStore.tel == tel)
    exists = q.first()
    if exists:
        exists.updated_at = datetime.utcnow()
        return

    db.add(
        UnregisteredStore(
            store_name=store_name,
            biz_num=biz_num,
            address=address,
            tel=tel,
            status="TEMP_VALID",
            source_submission_id=submission_id,
            updated_at=datetime.utcnow(),
        )
    )


def _fail_message(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    msg = {
        "BIZ_001": "BIZ_001 (중복 등록)",
        "BIZ_002": "BIZ_002 (2026년 결제일 아님)",
        "BIZ_003": "BIZ_003 (최소 금액 미달)",
        "BIZ_004": "BIZ_004 (강원특별자치도 외 지역)",
        "BIZ_005": "BIZ_005 (캠페인 기간 아님)",
        "BIZ_006": "BIZ_006 (캠페인 대상 지역 아님)",
        "BIZ_007": "BIZ_007 (입력 금액과 OCR 금액 불일치)",
        "BIZ_008": "BIZ_008 (유흥업소 등 부적격 업종)",
        "BIZ_010": "BIZ_010 (문서 구성 요건 불충족)",
        "BIZ_011": "BIZ_011 (영수증/증빙 금액 불일치)",
        "OCR_001": "OCR_001 (영수증 판독 불가)",
        "OCR_002": "OCR_002 (결제일 형식 오류)",
        "OCR_003": "OCR_003 (마스터 상호 미등록)",
        "PENDING_NEW": "PENDING_NEW (신규 상점 검수 대기)",
        "PENDING_VERIFICATION": "PENDING_VERIFICATION (사용자 입력값- OCR 불일치)",
        "UNFIT_CATEGORY": "UNFIT_CATEGORY (제외 업종)",
        "UNFIT_REGION": "UNFIT_REGION (지역 불일치)",
        "UNFIT_DATE": "UNFIT_DATE (기간/날짜 불일치)",
        "UNFIT_DUPLICATE": "UNFIT_DUPLICATE (중복 제출)",
        "ERROR_OCR": "ERROR_OCR (판독 불가)",
    }
    return msg.get(code, code)


def _normalize_error_code(code: Optional[str]) -> Optional[str]:
    """에러 문자열에서 표준 코드 토큰 추출."""
    if not code:
        return None
    m = re.search(
        r"\b((?:BIZ|OCR)_[0-9]{3}|PENDING_NEW|PENDING_VERIFICATION|UNFIT_CATEGORY|UNFIT_REGION|UNFIT_DATE|UNFIT_DUPLICATE|ERROR_OCR)\b",
        str(code),
    )
    return m.group(1) if m else None


def _global_fail_reason(code: Optional[str]) -> Optional[str]:
    """submission(마스터) 단위 fail reason 표준화."""
    if not code:
        return None
    mapping = {
        "BIZ_003": "UNFIT_TOTAL_AMOUNT (BIZ_003, 합산 금액 미달)",
        "BIZ_011": "UNFIT_STAY_MISMATCH (BIZ_011, 숙박-증빙 불일치)",
        "BIZ_004": "UNFIT_REGION (BIZ_004, 지역 불일치)",
        "BIZ_002": "UNFIT_DATE (BIZ_002, 결제일/기간 오류)",
        "PENDING_NEW": "PENDING_NEW (신규 상점 확인 필요)",
        "PENDING_VERIFICATION": "PENDING_VERIFICATION (입력값- OCR 불일치)",
        "UNFIT_CATEGORY": "UNFIT_CATEGORY (제외 업종)",
        "UNFIT_DUPLICATE": "UNFIT_DUPLICATE (중복 제출)",
        "ERROR_OCR": "ERROR_OCR (판독 불가)",
    }
    return mapping.get(code, _fail_message(code))


def _status_for_code(code: Optional[str]) -> str:
    """에러 코드에 대응하는 item/submission 상태명을 반환."""
    c = _normalize_error_code(code) or code
    if not c:
        return "FIT"
    if c in ("OCR_001", "ERROR_OCR"):
        return "ERROR_OCR"
    if c in ("BIZ_004", "UNFIT_REGION"):
        return "UNFIT_REGION"
    if c in ("BIZ_002", "OCR_002", "UNFIT_DATE"):
        return "UNFIT_DATE"
    if c in ("BIZ_001", "UNFIT_DUPLICATE"):
        return "UNFIT_DUPLICATE"
    if c in ("BIZ_008", "UNFIT_CATEGORY"):
        return "UNFIT_CATEGORY"
    if c == "PENDING_NEW":
        return "PENDING_NEW"
    if c == "PENDING_VERIFICATION":
        return "PENDING_VERIFICATION"
    if c.startswith("BIZ_"):
        return "UNFIT"
    return "UNFIT"


def map_ocr_to_db(
    submission_id: str,
    ocr_assets: List[Dict[str, Any]],
    documents: List[Dict[str, str]],
) -> Tuple[List[ReceiptItem], int]:
    """
    OCR 결과를 ReceiptItem 모델에 매핑하고, FIT 항목 합산 금액을 계산.
    - 카드번호 미인식/비정상: 0000 정규화
    - amount는 status == FIT 인 항목만 합산
    """
    items: List[ReceiptItem] = []
    total_fit_amount = 0
    for idx, asset in enumerate(ocr_assets, start=1):
        p = asset.get("parsed") or {}
        status = asset.get("status", "PENDING")
        amount = p.get("amount") if isinstance(p.get("amount"), int) else None
        card_num = _normalize_card_num(p.get("cardNum"))
        item = ReceiptItem(
            submission_id=submission_id,
            seq_no=idx,
            doc_type=asset.get("docType", (documents[idx - 1].get("docType") if idx - 1 < len(documents) else "RECEIPT")),
            image_key=(asset.get("imageKey") or "").strip(),
            store_name=(p.get("storeName") or "").strip() or None,
            biz_num=(p.get("businessNum") or "").strip() or None,
            pay_date=(p.get("payDate") or "").strip() or None,
            amount=amount,
            address=(p.get("address") or "").strip() or None,
            location=(p.get("location") or "").strip() or None,
            card_num=card_num,
            status=status,
            error_code=_normalize_error_code(asset.get("error_code")),
            error_message=_fail_message(_normalize_error_code(asset.get("error_code"))),
            confidence_score=p.get("confidenceScore") if isinstance(p.get("confidenceScore"), int) else None,
            ocr_raw=asset.get("ocrRaw"),
            parsed=p,
        )
        if status == "FIT" and isinstance(amount, int):
            total_fit_amount += amount
        items.append(item)
    return items, total_fit_amount


def finalize_submission(submission: Submission, total_amount: int, min_criteria: int, fail_code: Optional[str]) -> None:
    """
    submission 최종 판정/감사로그 저장.
    - FIT item 금액 합산 기준으로 최종 판정
    """
    submission.total_amount = total_amount
    resolved = _normalize_error_code(fail_code) or fail_code
    if not resolved and total_amount >= min_criteria:
        submission.status = "FIT"
        submission.global_fail_reason = None
        submission.fail_reason = None
    elif resolved in ("PENDING_NEW", "PENDING_VERIFICATION"):
        submission.status = resolved
        reason = _global_fail_reason(resolved)
        submission.global_fail_reason = reason
        submission.fail_reason = reason
    elif resolved in ("UNFIT_CATEGORY", "UNFIT_REGION", "UNFIT_DATE", "UNFIT_DUPLICATE", "ERROR_OCR"):
        submission.status = resolved
        reason = _global_fail_reason(resolved)
        submission.global_fail_reason = reason
        submission.fail_reason = reason
    else:
        submission.status = _status_for_code(resolved or "BIZ_003")
        reason = _global_fail_reason(resolved or "BIZ_003")
        submission.global_fail_reason = reason
        submission.fail_reason = reason


def _build_documents_from_request(req: CompleteRequest) -> List[Dict[str, str]]:
    if req.documents:
        return [
            {"imageKey": (d.imageKey or "").strip(), "docType": d.docType}
            for d in req.documents
        ]

    # 하위호환: 기존 data 구조를 문서 배열로 변환
    docs: List[Dict[str, str]] = []
    if req.type == "STAY" and isinstance(req.data, StayData):
        docs.append({"imageKey": req.data.receiptImageKey.strip(), "docType": "RECEIPT"})
        if req.data.isOta and req.data.otaStatementKey:
            docs.append({"imageKey": req.data.otaStatementKey.strip(), "docType": "OTA_INVOICE"})
    elif req.type == "TOUR" and isinstance(req.data, TourData):
        for k in req.data.receiptImageKeys:
            docs.append({"imageKey": (k or "").strip(), "docType": "RECEIPT"})
    return docs


def _parse_ota_invoice_result(ocr_data: dict) -> Dict[str, Optional[Any]]:
    """
    OTA 명세서(일반 OCR 결과 포함)에서 핵심 값 추출.
    - amount: 총액/결제금액 패턴 우선, 없으면 큰 숫자 후보
    - stayStart/stayEnd: 날짜 1~2개
    - guestName: 예약자/투숙객 키워드 기반 추출
    """
    text_blob = json.dumps(ocr_data, ensure_ascii=False)
    amount: Optional[int] = None
    m = re.search(
        r"(총.?금액|결제.?금액|합계|total)[^0-9]{0,20}([0-9][0-9,]{2,})",
        text_blob,
        re.IGNORECASE,
    )
    if m:
        amount = int(re.sub(r"[^0-9]", "", m.group(2)))
    else:
        nums = [int(n.replace(",", "")) for n in re.findall(r"[0-9][0-9,]{4,}", text_blob)]
        if nums:
            amount = max(nums)

    dates = re.findall(r"20[0-9]{2}[./-][0-9]{1,2}[./-][0-9]{1,2}", text_blob)
    stay_start = dates[0] if len(dates) >= 1 else None
    stay_end = dates[1] if len(dates) >= 2 else None
    guest = None
    g = re.search(r"(예약자|투숙객|고객명|name)[^가-힣A-Za-z0-9]{0,8}([가-힣A-Za-z]{2,20})", text_blob, re.IGNORECASE)
    if g:
        guest = g.group(2)

    return {
        "amount": amount,
        "stayStart": stay_start,
        "stayEnd": stay_end,
        "guestName": guest,
    }


async def _run_ocr_for_document(receipt_id: str, image_key: str, doc_type: str) -> Dict[str, Any]:
    """단일 이미지 OCR 및 파싱."""
    image_key = (image_key or "").strip()
    if not image_key:
        raise ValueError("BIZ_010")
    image_bytes, content_type = _get_image_bytes_from_s3(image_key)
    image_bytes, content_type = _resize_and_compress_for_ocr(image_bytes, content_type)
    image_format = _image_format_from_content_type(content_type)
    ocr_data = await _call_naver_ocr_with_retry(image_bytes, receipt_id, image_format, retries=2)

    if doc_type == "RECEIPT":
        amount, pay_date, store_name, address, location = _parse_ocr_result(ocr_data)
        parsed = {
            "amount": amount,
            "payDate": pay_date,
            "storeName": store_name,
            "address": address,
            "location": location,
            "businessNum": _extract_business_num(ocr_data),
            "cardNum": _extract_card_num(ocr_data),
            "confidenceScore": _extract_confidence_score(ocr_data),
        }
    else:
        parsed = _parse_ota_invoice_result(ocr_data)
        parsed["cardNum"] = "0000"
        parsed["confidenceScore"] = _extract_confidence_score(ocr_data)

    return {
        "imageKey": image_key,
        "docType": doc_type,
        "parsed": parsed,
        "ocrRaw": ocr_data,
    }


async def analyze_receipt_task(req: CompleteRequest):
    """1:N 구조 기준 OCR 분석: submission(parent) + receipt_items(children) 자산화."""
    db = SessionLocal()
    submission = db.query(Submission).filter(Submission.submission_id == req.receiptId).first()
    if not submission:
        db.close()
        return

    try:
        documents = _build_documents_from_request(req)
        if not documents:
            submission.status = "UNFIT"
            submission.fail_reason = _global_fail_reason("BIZ_010")
            submission.global_fail_reason = submission.fail_reason
            submission.audit_log = "문서 구성 요건 불충족"
            submission.audit_trail = submission.audit_log
            db.commit()
            return

        submission.project_type = req.type
        submission.status = "VERIFYING"
        db.commit()

        # 1) 병렬 OCR 수행
        tasks = [
            _run_ocr_for_document(req.receiptId, d.get("imageKey", ""), d.get("docType", "RECEIPT"))
            for d in documents
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ocr_assets: List[Dict[str, Any]] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                ocr_assets.append(
                    {
                        "imageKey": documents[i]["imageKey"],
                        "docType": documents[i]["docType"],
                        "parsed": {},
                        "ocrRaw": None,
                        "status": "ERROR_OCR",
                        "error_code": "OCR_001",
                    }
                )
            else:
                r["status"] = "PENDING"
                r["error_code"] = None
                ocr_assets.append(r)

        # 2) 자식 테이블 개별 저장 (기존 동일 submission_id 아이템 교체)
        db.query(ReceiptItem).filter(ReceiptItem.submission_id == req.receiptId).delete(synchronize_session=False)
        mapped_items, _ = map_ocr_to_db(req.receiptId, ocr_assets, documents)
        item_rows: List[ReceiptItem] = mapped_items
        for item in item_rows:
            db.add(item)

        def mark_item(i: int, status: str, code: Optional[str]) -> None:
            normalized = _normalize_error_code(code) or code
            ocr_assets[i]["status"] = status
            ocr_assets[i]["error_code"] = normalized
            item_rows[i].status = status
            item_rows[i].error_code = normalized
            item_rows[i].error_message = _fail_message(normalized)

        fail_code: Optional[str] = None
        audit_lines: List[str] = []
        total_amount = 0

        # 3) 유형별 합산/검증 (item status/error_code 우선 결정 후 submission 집계)
        if req.type == "STAY":
            receipt_idx = [i for i, a in enumerate(ocr_assets) if a["docType"] == "RECEIPT"]
            ota_idx = [i for i, a in enumerate(ocr_assets) if a["docType"] == "OTA_INVOICE"]
            if len(receipt_idx) < 1 or len(receipt_idx) > 1 or len(ota_idx) > 1:
                fail_code = "BIZ_010"
                for i, a in enumerate(ocr_assets):
                    if a["status"] == "PENDING":
                        mark_item(i, "UNFIT", "BIZ_010")
            else:
                ri = receipt_idx[0]
                rp = ocr_assets[ri]["parsed"]
                ocr_amount = rp.get("amount")
                amount = ocr_amount
                pay_date = rp.get("payDate") or ""
                store_name = rp.get("storeName") or ""
                address = rp.get("address") or ""
                location = rp.get("location") or ""
                biz_num = rp.get("businessNum")
                card_num = _normalize_card_num(rp.get("cardNum"))
                confidence = rp.get("confidenceScore") if isinstance(rp.get("confidenceScore"), int) else 0

                # OCR 신뢰도가 낮으면 사용자 입력을 참조값으로 사용 (고신뢰 OCR은 그대로 우선)
                if confidence < OCR_CONFIDENCE_THRESHOLD and isinstance(req.data, StayData):
                    amount = req.data.amount
                    pay_date = req.data.payDate or pay_date
                    location = req.data.location or location
                    rp["amount"] = amount
                    rp["payDate"] = pay_date
                    rp["location"] = location
                    item_rows[ri].amount = amount
                    item_rows[ri].pay_date = pay_date
                    item_rows[ri].location = location

                if ocr_assets[ri]["status"] == "ERROR_OCR":
                    fail_code = "ERROR_OCR"
                elif amount is None:
                    mark_item(ri, "ERROR_OCR", "OCR_001")
                    fail_code = "ERROR_OCR"
                else:
                    _, normalized_date = _normalize_and_validate_2026_date(pay_date)
                    pay_date_stored = normalized_date or pay_date
                    item_fail: Optional[str] = None
                    if _ocr_contains_forbidden_business(ocr_assets[ri]["ocrRaw"]):
                        item_fail = "BIZ_008"
                    if not item_fail:
                        _, fc = validate_and_match(
                            db,
                            store_name,
                            address,
                            pay_date,
                            amount,
                            location,
                            amount,
                            "STAY",
                            is_2026_date=bool(normalized_date),
                        )
                        if fc:
                            if fc == "OCR_003":
                                _register_new_candidate_store(db, req.receiptId, rp, ocr_assets[ri]["ocrRaw"])
                                item_fail = "PENDING_NEW"
                            else:
                                item_fail = fc
                    if not item_fail and _check_duplicate_receipt_item(
                        db, req.receiptId, biz_num, pay_date_stored, amount, card_num
                    ):
                        item_fail = "BIZ_001"
                    if not item_fail and req.campaignId:
                        ok, c_fail = validate_campaign_rules(db, req.campaignId, location, pay_date_stored)
                        if not ok and c_fail:
                            item_fail = c_fail

                    # 사용자 입력 대비 OCR 금액 10% 이상 차이 시 수동검증 보류
                    if not item_fail and isinstance(req.data, StayData):
                        base_amount = ocr_amount if isinstance(ocr_amount, int) else amount
                        if _is_amount_mismatch(req.data.amount, base_amount):
                            item_fail = "PENDING_VERIFICATION"

                    if item_fail:
                        mark_item(ri, _status_for_code(item_fail), item_fail)
                        fail_code = item_fail
                    else:
                        mark_item(ri, "FIT", None)
                        total_amount = amount

                if ota_idx:
                    oi = ota_idx[0]
                    if fail_code and total_amount <= 0:
                        if ocr_assets[oi]["status"] == "PENDING":
                            mark_item(oi, _status_for_code(fail_code), fail_code)
                    elif ocr_assets[oi]["status"] == "ERROR_OCR":
                        fail_code = fail_code or (ocr_assets[oi]["error_code"] or "OCR_001")
                    else:
                        op = ocr_assets[oi]["parsed"]
                        ota_amount = op.get("amount")
                        if total_amount and ota_amount is not None and ota_amount != total_amount:
                            mark_item(oi, _status_for_code("BIZ_011"), "BIZ_011")
                            fail_code = fail_code or "BIZ_011"
                        else:
                            mark_item(oi, "FIT", None)
                            audit_lines.append(f"영수증 금액({total_amount}) = 명세서 금액({ota_amount}) 일치")

        else:  # TOUR
            receipt_idx = [i for i, a in enumerate(ocr_assets) if a["docType"] == "RECEIPT"]
            if len(receipt_idx) < 1 or len(receipt_idx) > 3:
                fail_code = "BIZ_010"
                for i, a in enumerate(ocr_assets):
                    if a["status"] == "PENDING":
                        mark_item(i, "UNFIT", "BIZ_010")
            else:
                total = 0
                amount_parts: List[str] = []
                for i in receipt_idx:
                    a = ocr_assets[i]
                    p = a["parsed"]
                    amount = p.get("amount")
                    pay_date = p.get("payDate") or ""
                    store_name = p.get("storeName") or ""
                    address = p.get("address") or ""
                    location = p.get("location") or ""
                    biz_num = p.get("businessNum")
                    card_num = _normalize_card_num(p.get("cardNum"))

                    if a["status"] == "ERROR_OCR":
                        continue
                    if amount is None:
                        mark_item(i, "ERROR_OCR", "OCR_001")
                        continue

                    is_2026, norm_date = _normalize_and_validate_2026_date(pay_date)
                    pay_date_stored = norm_date or pay_date
                    item_fail: Optional[str] = None
                    if not is_2026:
                        item_fail = "BIZ_002"
                    elif address and "강원" not in address:
                        item_fail = "BIZ_004"
                    elif _ocr_contains_forbidden_business(a["ocrRaw"]):
                        item_fail = "BIZ_008"
                    else:
                        matched, _ = match_store_in_master(db, store_name, location)
                        if not matched:
                            _register_new_candidate_store(db, req.receiptId, p, a["ocrRaw"])
                            item_fail = "PENDING_NEW"

                    if not item_fail and _check_duplicate_receipt_item(
                        db, req.receiptId, biz_num, pay_date_stored, amount, card_num
                    ):
                        item_fail = "BIZ_001"
                    if not item_fail and req.campaignId:
                        ok, c_fail = validate_campaign_rules(db, req.campaignId, location, pay_date_stored)
                        if not ok and c_fail:
                            item_fail = c_fail

                    if item_fail:
                        mark_item(i, _status_for_code(item_fail), item_fail)
                        continue

                    mark_item(i, "FIT", None)
                    total += amount
                    amount_parts.append(str(amount))

                total_amount = total
                if isinstance(req.data, TourData) and _is_amount_mismatch(req.data.amount, total_amount):
                    for i in receipt_idx:
                        if ocr_assets[i].get("status") == "FIT":
                            mark_item(i, "PENDING_VERIFICATION", "PENDING_VERIFICATION")
                    fail_code = fail_code or "PENDING_VERIFICATION"
                if total_amount < 50000:
                    fail_code = "BIZ_003"
                audit_lines.append(
                    f"영수증 {len(receipt_idx)}매 중 적격 합산: "
                    f"{' + '.join(amount_parts) if amount_parts else '0'} = {total_amount}"
                )

        fit_cnt = sum(1 for a in ocr_assets if a.get("status") == "FIT")
        unfit_cnt = sum(1 for a in ocr_assets if str(a.get("status", "")).startswith("UNFIT"))
        err_cnt = sum(1 for a in ocr_assets if a.get("status") in ("ERROR", "ERROR_OCR"))
        pending_new_cnt = sum(1 for a in ocr_assets if a.get("status") == "PENDING_NEW")
        pending_verification_cnt = sum(1 for a in ocr_assets if a.get("status") == "PENDING_VERIFICATION")
        if not fail_code and pending_new_cnt > 0:
            fail_code = "PENDING_NEW"
        if not fail_code and pending_verification_cnt > 0:
            fail_code = "PENDING_VERIFICATION"
        audit_lines.append(
            f"총 {len(ocr_assets)}매 중 적격 {fit_cnt}매, 부적격 {unfit_cnt}매, 오류 {err_cnt}매, "
            f"신규상점대기 {pending_new_cnt}매, 수동검증대기 {pending_verification_cnt}매"
        )

        # 4) 부모 상태 업데이트
        min_criteria = 60000 if req.type == "STAY" else 50000
        finalize_submission(submission, total_amount, min_criteria, fail_code)
        submission.audit_log = " | ".join(audit_lines) if audit_lines else (submission.fail_reason or "")
        submission.audit_trail = submission.audit_log
        db.commit()

    except Exception as e:
        logger.error("analyze_receipt_task failed: %s", e, exc_info=True)
        submission.status = "ERROR"
        submission.fail_reason = str(e)
        submission.global_fail_reason = submission.fail_reason
        submission.audit_log = "complete 처리 중 예외 발생"
        submission.audit_trail = submission.audit_log
        db.commit()
    finally:
        db.close()