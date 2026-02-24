import io
import os
import re
import time
import uuid
import json
import httpx
import boto3
from PIL import Image
from datetime import datetime
from typing import Any, Dict, List, Optional, Union, Tuple
from dotenv import load_dotenv
from dateutil import parser as dateutil_parser
from sqlalchemy import text as sql_text

from processor import validate_and_match, validate_campaign_rules, match_store_in_master
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
    status = Column(String, default="PENDING")  # PENDING → PROCESSING → VERIFYING → FIT | UNFIT | DUPLICATE | ERROR
    amount = Column(Integer)
    pay_date = Column(String)
    store_name = Column(String)
    address = Column(String)  # OCR 가맹점 주소 전체 (강원특별자치도 검증용)
    location = Column(String)  # 시군 정보 (데이터 자산화)
    image_key = Column(String)  # MinIO 객체 키 (영수증 이미지 경로)
    image_keys = Column(JSON)  # 제출된 전체 이미지 키 배열 (합산형)
    documents = Column(JSON)  # 문서 메타데이터 배열 [{imageKey, docType}]
    business_num = Column(String)  # 사업자등록번호 (OCR 추출)
    ocr_assets = Column(JSON)  # 이미지별 OCR 원본/파싱 결과 배열
    audit_trail = Column(String)  # 검증 근거 요약 문자열
    submission_type = Column(String)  # LEGACY_DATA | DOCUMENTS
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


class ReceiptMetadata(BaseModel):
    imageKey: str
    docType: str  # RECEIPT | OTA_INVOICE

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
    # 동일 fileName 반복 업로드 충돌 방지용 랜덤 접미사
    object_key = f"receipts/{receipt_id}_{uuid.uuid4().hex[:8]}_{fileName}"
    # 설계안: 업로드 URL 10분 유효 (PROJECT/전 단계 JSON API 설계안.md)
    url = s3_client.generate_presigned_url(
        "put_object",
        Params={"Bucket": S3_BUCKET, "Key": object_key, "ContentType": contentType},
        ExpiresIn=600,  # 10분
    )
    
    existing = db.query(Receipt).filter(Receipt.receipt_id == receipt_id).first()
    if existing:
        if existing.user_uuid != userUuid:
            raise HTTPException(status_code=403, detail="receiptId owner mismatch")
        existing.type = type
    else:
        db.add(Receipt(receipt_id=receipt_id, user_uuid=userUuid, type=type, status="PENDING"))
    db.commit()
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
    """3단계: 사용자 입력값 수신 및 비동기 분석 시작 (합산형 documents 지원)"""
    receipt = db.query(Receipt).filter(Receipt.receipt_id == req.receiptId).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    if receipt.user_uuid != req.userUuid:
        raise HTTPException(status_code=403, detail="receiptId owner mismatch")

    if receipt.status in ("FIT", "UNFIT", "DUPLICATE", "ERROR"):
        raise HTTPException(status_code=409, detail="Receipt already completed")

    if receipt.status in ("PROCESSING", "VERIFYING"):
        return {"status": receipt.status, "receiptId": req.receiptId}

    receipt.status = "PROCESSING"
    db.commit()

    background_tasks.add_task(analyze_receipt_task, req)
    return {"status": "PROCESSING", "receiptId": req.receiptId}

class StatusResponse(BaseModel):
    status: Optional[str] = None
    amount: Optional[int] = None
    failReason: Optional[str] = None
    rewardAmount: int = 0
    address: Optional[str] = None  # 가맹점 주소(시군 또는 주소)
    cardPrefix: Optional[str] = None  # 카드 앞 4자리(비식별화)

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
    receipt = db.query(Receipt).filter(Receipt.receipt_id == receipt_id).first()
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
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
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
        # 결제 금액 (₩, 콤마, 원 등 제거 후 숫자만 추출)
        price_text = (result.get("totalPrice") or {}).get("price") or {}
        raw_price = (price_text.get("text") or "0").strip()
        amount_str = re.sub(r"[^0-9]", "", raw_price)
        amount = int(amount_str) if amount_str else None
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


# 유흥업소 등 부적격 업태 키워드 (BIZ_008)
FORBIDDEN_BUSINESS_KEYWORDS = ("단란주점", "유흥주점", "유흥주점영업", "무도장", "사교춤장")


def _ocr_contains_forbidden_business(ocr_data: dict) -> bool:
    """OCR 결과 전체 텍스트에서 부적격 업태 키워드 포함 여부. 포함 시 True."""
    try:
        text = json.dumps(ocr_data, ensure_ascii=False)
        return any(kw in text for kw in FORBIDDEN_BUSINESS_KEYWORDS)
    except Exception:
        return False


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
    }
    return msg.get(code, code)


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


async def analyze_receipt_task(req: CompleteRequest):
    """합산형 제출(Documents) 기준 OCR 분석 및 유형별 검증 → 자산화."""
    db = SessionLocal()
    receipt = db.query(Receipt).filter(Receipt.receipt_id == req.receiptId).first()
    if not receipt:
        db.close()
        return

    try:
        documents = _build_documents_from_request(req)
        if not documents:
            receipt.status = "UNFIT"
            receipt.fail_reason = _fail_message("BIZ_010")
            db.commit()
            return

        receipt.submission_type = "DOCUMENTS" if req.documents else "LEGACY_DATA"
        receipt.documents = documents
        receipt.image_keys = [d["imageKey"] for d in documents]
        receipt.image_key = documents[0]["imageKey"]
        receipt.status = "VERIFYING"
        db.commit()

        ocr_assets: List[Dict[str, Any]] = []
        fail_code: Optional[str] = None
        audit_lines: List[str] = []

        # 1) 문서별 OCR
        for d in documents:
            image_key = (d.get("imageKey") or "").strip()
            doc_type = d.get("docType", "RECEIPT")
            if not image_key:
                receipt.status = "UNFIT"
                receipt.fail_reason = _fail_message("BIZ_010")
                db.commit()
                return
            try:
                image_bytes, content_type = _get_image_bytes_from_s3(image_key)
            except Exception as e:
                receipt.status = "ERROR"
                receipt.fail_reason = f"OCR_001 (이미지 로드 실패: {e})"
                db.commit()
                return

            image_bytes, content_type = _resize_and_compress_for_ocr(image_bytes, content_type)
            image_format = _image_format_from_content_type(content_type)
            try:
                ocr_data = await _call_naver_ocr_binary(image_bytes, req.receiptId, image_format)
            except Exception as e:
                receipt.status = "ERROR"
                receipt.fail_reason = f"OCR_001 (OCR request failed: {e})"
                db.commit()
                return

            if doc_type == "RECEIPT":
                amount, pay_date, store_name, address, location = _parse_ocr_result(ocr_data)
                parsed = {
                    "amount": amount,
                    "payDate": pay_date,
                    "storeName": store_name,
                    "address": address,
                    "location": location,
                    "businessNum": _extract_business_num(ocr_data),
                }
            else:
                parsed = _parse_ota_invoice_result(ocr_data)

            ocr_assets.append(
                {
                    "imageKey": image_key,
                    "docType": doc_type,
                    "parsed": parsed,
                    "ocrRaw": ocr_data,
                }
            )

        receipt.ocr_assets = ocr_assets
        receipt.ocr_raw = ocr_assets[0]["ocrRaw"] if ocr_assets else None

        # 2) 유형별 검증 엔진
        if req.type == "STAY":
            receipt_docs = [a for a in ocr_assets if a["docType"] == "RECEIPT"]
            ota_docs = [a for a in ocr_assets if a["docType"] == "OTA_INVOICE"]
            if len(receipt_docs) < 1 or len(receipt_docs) > 1 or len(ota_docs) > 1:
                fail_code = "BIZ_010"
            else:
                rp = receipt_docs[0]["parsed"]
                amount = rp.get("amount")
                pay_date = rp.get("payDate") or ""
                store_name = rp.get("storeName") or ""
                address = rp.get("address") or ""
                location = rp.get("location") or ""
                business_num = rp.get("businessNum")

                if amount is None:
                    fail_code = "OCR_001"
                else:
                    _, normalized_date = _normalize_and_validate_2026_date(pay_date)
                    pay_date_stored = normalized_date or pay_date
                    receipt.amount = amount
                    receipt.pay_date = pay_date_stored
                    receipt.store_name = store_name
                    receipt.address = address
                    receipt.location = location
                    receipt.business_num = business_num
                    receipt.card_prefix = req.data.cardPrefix if isinstance(req.data, StayData) else ""

                    if _ocr_contains_forbidden_business(receipt_docs[0]["ocrRaw"]):
                        fail_code = "BIZ_008"

                    if not fail_code:
                        _, fc = validate_and_match(
                            db,
                            store_name,
                            address,
                            pay_date,
                            amount,
                            location,
                            amount,  # 합산형에서는 OCR 추출금액 자체를 기준으로 검증
                            "STAY",
                            is_2026_date=bool(normalized_date),
                        )
                        if fc:
                            fail_code = fc

                    if not fail_code and receipt.card_prefix:
                        if _check_duplicate_receipt(db, store_name, pay_date_stored, amount, receipt.card_prefix):
                            fail_code = "BIZ_001"

                    if not fail_code and req.campaignId:
                        ok, c_fail = validate_campaign_rules(db, req.campaignId, location, pay_date_stored)
                        if not ok and c_fail:
                            fail_code = c_fail

                    if not fail_code and ota_docs:
                        op = ota_docs[0]["parsed"]
                        ota_amount = op.get("amount")
                        if ota_amount is not None and ota_amount != amount:
                            fail_code = "BIZ_011"
                        else:
                            audit_lines.append(f"영수증 금액({amount}) = 명세서 금액({ota_amount}) 일치")

                        for dtx in [op.get("stayStart"), op.get("stayEnd")]:
                            if dtx:
                                is_2026, _ = _normalize_and_validate_2026_date(str(dtx))
                                if not is_2026:
                                    fail_code = fail_code or "BIZ_002"
                                    break
                        if op.get("guestName"):
                            audit_lines.append("예약자명 추출됨(실명-UUID 자동대조는 현재 스킵)")

        else:  # TOUR
            receipt_docs = [a for a in ocr_assets if a["docType"] == "RECEIPT"]
            if len(receipt_docs) < 1 or len(receipt_docs) > 3:
                fail_code = "BIZ_010"
            else:
                total = 0
                biz_nums: set[str] = set()
                amount_parts: List[str] = []
                first_loc = ""
                first_date = ""
                first_store = ""
                first_addr = ""
                first_card_prefix = req.data.cardPrefix if isinstance(req.data, TourData) else ""

                for idx, a in enumerate(receipt_docs):
                    p = a["parsed"]
                    amount = p.get("amount")
                    pay_date = p.get("payDate") or ""
                    store_name = p.get("storeName") or ""
                    address = p.get("address") or ""
                    location = p.get("location") or ""
                    biz_num = p.get("businessNum")

                    if amount is None:
                        fail_code = "OCR_001"
                        break
                    total += amount
                    amount_parts.append(str(amount))

                    is_2026, norm_date = _normalize_and_validate_2026_date(pay_date)
                    if not is_2026:
                        fail_code = "BIZ_002"
                        break
                    if address and "강원" not in address:
                        fail_code = "BIZ_004"
                        break
                    if _ocr_contains_forbidden_business(a["ocrRaw"]):
                        fail_code = "BIZ_008"
                        break

                    matched, _ = match_store_in_master(db, store_name, location)
                    if not matched:
                        fail_code = "OCR_003"
                        break

                    if biz_num:
                        if biz_num in biz_nums:
                            fail_code = "BIZ_001"
                            break
                        biz_nums.add(biz_num)

                    if req.campaignId:
                        ok, c_fail = validate_campaign_rules(db, req.campaignId, location, norm_date or pay_date)
                        if not ok and c_fail:
                            fail_code = c_fail
                            break

                    if idx == 0:
                        first_loc = location
                        first_date = norm_date or pay_date
                        first_store = store_name
                        first_addr = address

                if not fail_code and total < 50000:
                    fail_code = "BIZ_003"

                receipt.amount = total
                receipt.pay_date = first_date
                receipt.store_name = first_store
                receipt.address = first_addr
                receipt.location = first_loc
                receipt.business_num = ",".join(sorted(biz_nums)) if biz_nums else None
                receipt.card_prefix = first_card_prefix
                audit_lines.append(f"영수증 {len(receipt_docs)}매 합산: {' + '.join(amount_parts)} = {total}")

        receipt.audit_trail = " | ".join(audit_lines) if audit_lines else None
        receipt.status = "FIT" if not fail_code else "UNFIT"
        receipt.fail_reason = _fail_message(fail_code)
        db.commit()

    except Exception as e:
        receipt.status = "ERROR"
        receipt.fail_reason = str(e)
        db.commit()
    finally:
        db.close()