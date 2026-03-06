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
from datetime import datetime, date, timedelta, timezone
from typing import Any, Dict, List, Optional, Union, Tuple, Literal
from dotenv import load_dotenv
from dateutil import parser as dateutil_parser
from sqlalchemy import text as sql_text, func

from processor import validate_and_match, validate_campaign_rules, match_store_in_master
from store_classifier import (
    classify_store,
    is_forbidden as _classifier_is_forbidden,
    AUTO_REGISTER_THRESHOLD as CLASSIFIER_AUTO_THRESHOLD,
)
from fastapi import FastAPI, File, Form, HTTPException, BackgroundTasks, Depends, UploadFile, Header, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator, UUID4, ConfigDict
from sqlalchemy import create_engine, Column, String, Integer, BigInteger, Float, DateTime, JSON, Boolean, ARRAY, ForeignKey, update, case
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
# 분석 완료 시 FE 결과 수신 URL (운영: https://easy.gwd.go.kr/dg/coupon/api/ocr/result / 테스트: http://210.179.205.50/dg/coupon/api/ocr/result)
OCR_RESULT_CALLBACK_URL = os.getenv("OCR_RESULT_CALLBACK_URL", "").strip() or None
OCR_CALLBACK_TIMEOUT_SEC = 10
OCR_CALLBACK_SCHEMA_VERSION = 2
OCR_CALLBACK_MAX_AUDIT_TRAIL_CHARS = int(os.getenv("OCR_CALLBACK_MAX_AUDIT_TRAIL_CHARS", "2000"))
OCR_CALLBACK_MAX_ERROR_MESSAGE_CHARS = int(os.getenv("OCR_CALLBACK_MAX_ERROR_MESSAGE_CHARS", "200"))
NAVER_OCR_SECRET = os.getenv("NAVER_OCR_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# 관리자 API 보호(선택): 설정 시 /api/v1/admin/* 호출에 X-Admin-Key 필요
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip() or None

# 캠페인 라우팅(확장 포인트)
# - FE가 campaignId를 결정/관리하지 않도록, 서버가 캠페인을 선택해 submission.campaign_id에 고정한다.
# - 현재는 DEFAULT_CAMPAIGN_ID(기본 1) 중심으로 운영하되, campaigns 테이블 기반으로 확장 가능.
DEFAULT_CAMPAIGN_ID = int(os.getenv("DEFAULT_CAMPAIGN_ID", "1"))

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
    user_input_snapshot = Column(JSONB, nullable=True)  # Complete 시 FE가 보낸 data (방식2: items[])
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # VERIFYING 타임아웃 등 판단용
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
    occurrence_count = Column(Integer, default=1)  # 동일 상점 영수증 접수 횟수
    first_detected_at = Column(DateTime)
    recent_receipt_id = Column(String(64), index=True)  # 증거 확인용 최근 submission_id
    predicted_category = Column(String(64))  # OCR/분류용 (nullable)
    category_confidence = Column(Float)  # 0.0~1.0 (자동 분류 신뢰도)
    classifier_type = Column(String(20))  # RULE | SEMANTIC | AI
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class JudgmentRuleConfig(Base):
    __tablename__ = "judgment_rule_config"
    id = Column(Integer, primary_key=True, default=1)
    unknown_store_policy = Column(String(32), default="AUTO_REGISTER")  # 기본: 자동 상점추가(데이터 자산화). PENDING_NEW=검수 대기
    auto_register_threshold = Column(Float, default=0.90)  # 0.0 ~ 1.0
    enable_gemini_classifier = Column(Boolean, default=True)
    min_amount_stay = Column(Integer, default=60000)
    min_amount_tour = Column(Integer, default=50000)
    # MinIO–DB 정합: 고아 객체/만료 후보 유효기간. 분 단위 우선, 없으면 일 단위 사용
    orphan_object_days = Column(Integer, default=1)       # 하위 호환
    expired_candidate_days = Column(Integer, default=1)   # 하위 호환
    orphan_object_minutes = Column(Integer, default=1440)   # 1440 = 1일. NULL이면 orphan_object_days*1440
    expired_candidate_minutes = Column(Integer, default=1440)
    verifying_timeout_minutes = Column(Integer, default=0)   # 0 = 비활성. VERIFYING 대기 허용(분)
    verifying_timeout_action = Column(String(16), default="UNFIT")  # UNFIT | ERROR
    updated_at = Column(DateTime, default=datetime.utcnow)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor = Column(String(128))
    action = Column(String(64), nullable=False)       # RULE_UPDATE | CANDIDATE_APPROVE | SUBMISSION_OVERRIDE | CALLBACK_SEND | CALLBACK_RESEND | CALLBACK_VERIFY
    target_type = Column(String(64))                  # judgment_rule_config | unregistered_store | submission
    target_id = Column(String(128))
    before_json = Column(JSONB)
    after_json = Column(JSONB)
    meta = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)


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
    OCR_004 = "OCR_004"  # 인식 불량(핵심 필드 누락 또는 저신뢰도) → 수동 검수 보정
    PENDING_NEW = "PENDING_NEW"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    UNFIT_CATEGORY = "UNFIT_CATEGORY"
    UNFIT_REGION = "UNFIT_REGION"
    UNFIT_DATE = "UNFIT_DATE"
    UNFIT_DUPLICATE = "UNFIT_DUPLICATE"
    ERROR_OCR = "ERROR_OCR"


class StayData(BaseModel):
    location: Optional[str] = None
    payDate: str
    amount: int
    cardPrefix: str
    receiptImageKey: str
    isOta: bool = False
    otaStatementKey: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "deprecated": True,
            "description": "(Legacy) FE 수기 입력 보정용(STAY). 신규 FE 구현은 documents-only(v2) 사용 권장.",
        }
    )

class TourData(BaseModel):
    storeName: str
    payDate: str
    amount: int
    cardPrefix: str
    receiptImageKeys: List[str] # 최대 3장 배열 처리

    model_config = ConfigDict(
        json_schema_extra={
            "deprecated": True,
            "description": "(Legacy) FE 수기 입력 보정용(TOUR). 신규 FE 구현은 documents-only(v2) 사용 권장.",
        }
    )


class PerDocumentFormData(BaseModel):
    """장별 사용자 입력 (방식2). documents[i]와 data.items[i] 1:1 대응."""
    amount: int
    payDate: str
    storeName: Optional[str] = None
    location: Optional[str] = None
    cardPrefix: Optional[str] = None


class DataWithItems(BaseModel):
    """방식2: 여러 폼데이터. items[]는 documents[]와 동일 순서·길이."""
    items: List[PerDocumentFormData]


class ReceiptMetadata(BaseModel):
    imageKey: str
    docType: Literal["RECEIPT", "OTA_INVOICE"]

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
    type: ProjectType
    campaignId: Optional[int] = Field(
        default=None,
        description="(Internal/Legacy) 캠페인 식별자. 서버가 presigned 단계에서 캠페인을 선택해 submission에 고정하므로, "
        "FE 신규 연동에서는 생략 권장(서버가 저장된 campaign_id를 사용).",
        json_schema_extra={"deprecated": True},
    )
    data: Optional[Union[StayData, TourData, DataWithItems]] = Field(
        default=None,
        description="FE 수기 입력. 방식2: data.items[] (documents와 동일 순서). 레거시: StayData/TourData 단일 객체.",
    )
    documents: Optional[List[ReceiptMetadata]] = None

    @model_validator(mode="before")
    @classmethod
    def validate_data_by_type(cls, v):
        """type에 따라 data를 StayData / TourData / DataWithItems 로 검증."""
        if not isinstance(v, dict) or "type" not in v:
            return v
        t = v.get("type")
        if isinstance(t, ProjectType):
            t = t.value
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
            if "items" in data and isinstance(data.get("items"), list):
                v["data"] = DataWithItems.model_validate(data)
                if v.get("documents") is not None and len(v["data"].items) != len(v["documents"]):
                    raise ValueError("data.items length must match documents length")
            elif t == "STAY":
                v["data"] = StayData.model_validate(data)
            elif t == "TOUR":
                v["data"] = TourData.model_validate(data)

        if v.get("documents") is None and v.get("data") is None:
            raise ValueError("Either documents or legacy data is required")

        return v


class CompleteRequestV2(BaseModel):
    """
    FE 연동 전용. documents 필수, data(방식2: items[]) 선택.
    - data 사용 시 data.items[]는 documents와 동일 순서·길이.
    """

    receiptId: str
    userUuid: str
    type: ProjectType
    documents: List[ReceiptMetadata]
    data: Optional[DataWithItems] = None

    @model_validator(mode="before")
    @classmethod
    def validate_documents_by_type(cls, v):
        if not isinstance(v, dict) or "type" not in v:
            return v
        t = v.get("type")
        if isinstance(t, ProjectType):
            t = t.value
        docs = v.get("documents")
        data = v.get("data")
        if t not in ("STAY", "TOUR"):
            raise ValueError("type must be STAY or TOUR")
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

        if data is not None and isinstance(data, dict) and "items" in data:
            v["data"] = DataWithItems.model_validate(data)
            if len(v["data"].items) != len(normalized_docs):
                raise ValueError("data.items length must match documents length")
        else:
            v["data"] = None

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

        return v

# 5. API 엔드포인트 (Swagger 태그 구성)
OPENAPI_TAGS = [
    {
        "name": "FE - Step 1: Presigned URL",
        "description": "신청(receiptId) 생성 및 이미지 업로드용 presigned URL 발급",
    },
    {
        "name": "FE - Step 1b: Upload (fallback)",
        "description": "스토리지 CORS 불가 등 예외 상황에서 서버로 multipart 업로드(대안)",
    },
    {
        "name": "FE - Step 3: Complete",
        "description": "업로드된 objectKey 목록(documents)으로 분석 시작",
    },
    {
        "name": "FE - Step 6: Status",
        "description": "결과 조회(폴링/스케줄러 복구). 콜백 누락 대비",
    },
    {
        "name": "FE - Campaigns",
        "description": "(선택) 활성 캠페인 조회. 다중 캠페인 운영 확장 포인트",
    },
    {"name": "Admin - Rules", "description": "판정 규칙 운영(관리자)"},
    {"name": "Admin - Stores", "description": "신규 상점 후보군 관리/승인(관리자)"},
    {"name": "Admin - Submissions", "description": "신청 검색/상세/override/콜백 재전송(관리자)"},
    {"name": "Admin - Campaigns", "description": "캠페인 운영(관리자, 확장)"},
    {"name": "Admin - Callback", "description": "콜백 검증/재전송/로그(관리자)"},
    {"name": "Admin - Regions", "description": "행정구역(시도/시군구) 목록(관리자)"},
    {"name": "Admin - Stats", "description": "행정구역별 집계/통계(관리자)"},
    {"name": "Admin - Maps", "description": "행정지도 SVG URL(statgarten/maps, SGIS 기반)(관리자)"},
    {"name": "Admin - Jobs", "description": "운영 잡(VERIFYING 타임아웃 처리 등, 관리자/배치)"},
    {"name": "Ops", "description": "헬스 체크 등 운영용 엔드포인트"},
]

# 5-1. FastAPI 앱
app = FastAPI(
    title="GEMS OCR API",
    version="1.0.0",
    description="강원 여행 인센티브 영수증 인식 API",
    servers=[{"url": "https://api.nanum.online", "description": "Production"}],
    openapi_tags=OPENAPI_TAGS,
)
# CORS: FE/관리자 페이지 오리진 (관리자 페이지 169.254.240.5:8080 포함)
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").strip()
_cors_list = [
    "http://localhost:5173",
    "http://localhost:8080",
    "http://169.254.240.5:8080",
    "https://easy.gwd.go.kr",
    "https://api.nanum.online",
]
if CORS_ORIGINS:
    _cors_list = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()


def _parse_date_any(raw: Any) -> Optional[date]:
    """
    pay_date/campaign date 파싱.
    - 지원: date/datetime, 'YYYY-MM-DD', 'YYYY/MM/DD'
    """
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        s = s.replace("/", "-")
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except Exception:
            return None
    return None


def _city_matches_target(store_city: str, target_city: str) -> bool:
    store_city = (store_city or "").strip()
    target_city = (target_city or "").strip()
    if not target_city:
        return True
    if store_city == target_city:
        return True
    if target_city in store_city or store_city in target_city:
        return True
    target_key = target_city.replace("시", "").replace("군", "").strip()
    if target_key and (target_key in store_city or store_city.startswith(target_key)):
        return True
    return False


def _fetch_active_campaign_rows(db: Session) -> List[Dict[str, Any]]:
    """
    campaigns 테이블에서 활성 캠페인을 조회.
    - 컬럼 확장(priority, project_type, updated_at) 유무에 따라 안전하게 조회한다.
    """
    try:
        rows = db.execute(
            sql_text(
                "SELECT campaign_id, campaign_name, is_active, target_city_county, start_date, end_date, created_at, "
                "COALESCE(priority, 100) AS priority, project_type "
                "FROM campaigns WHERE is_active = true"
            )
        ).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        try:
            rows = db.execute(
                sql_text(
                    "SELECT campaign_id, campaign_name, is_active, target_city_county, start_date, end_date, created_at "
                    "FROM campaigns WHERE is_active = true"
                )
            ).mappings().all()
            items: List[Dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                d["priority"] = 100
                d["project_type"] = None
                items.append(d)
            return items
        except Exception:
            return []


def _resolve_campaign_id_for_presigned(db: Session, user_uuid: str, project_type: ProjectType) -> int:
    """
    Presigned 단계 캠페인 선택(보수적):
    - 이 시점엔 OCR location/pay_date가 없으므로, 지역 제한 없는(=target_city_county NULL) 활성 캠페인 중
      기간(start/end)이 '오늘'을 포함하는 캠페인을 우선 선택한다.
    - 없으면 DEFAULT_CAMPAIGN_ID로 fallback.
    """
    today = datetime.utcnow().date()
    pt = project_type.value if isinstance(project_type, ProjectType) else str(project_type)
    candidates = []
    for c in _fetch_active_campaign_rows(db):
        if c.get("project_type") and str(c.get("project_type")).strip() != pt:
            continue
        target = (c.get("target_city_county") or "").strip()
        if target:
            continue
        sd = _parse_date_any(c.get("start_date"))
        ed = _parse_date_any(c.get("end_date"))
        if sd and ed and not (sd <= today <= ed):
            continue
        candidates.append(c)
    if not candidates:
        return DEFAULT_CAMPAIGN_ID
    candidates.sort(key=lambda x: (int(x.get("priority") or 100), int(x.get("campaign_id") or 0)))
    return int(candidates[0].get("campaign_id") or DEFAULT_CAMPAIGN_ID)


def _resolve_campaign_id_for_receipt(
    db: Session, project_type: ProjectType, store_city: str, pay_date: str
) -> int:
    """
    OCR 결과(location/pay_date)가 확보된 이후 캠페인 선택(확장 핵심).
    - 활성 캠페인 중 (project_type 일치/NULL) + (기간 포함) + (target_city_county 매칭/NULL) 조건을 만족하는 후보 선택
    - 우선순위: (1) priority 낮은 값 (2) target_city_county가 있는 캠페인(지역 특화) (3) campaign_id 작은 값
    - 후보 없으면 DEFAULT_CAMPAIGN_ID
    """
    receipt_date = _parse_date_any(pay_date)
    pt = project_type.value if isinstance(project_type, ProjectType) else str(project_type)
    matches: List[Dict[str, Any]] = []
    for c in _fetch_active_campaign_rows(db):
        if c.get("project_type") and str(c.get("project_type")).strip() != pt:
            continue
        sd = _parse_date_any(c.get("start_date"))
        ed = _parse_date_any(c.get("end_date"))
        if receipt_date and sd and ed and not (sd <= receipt_date <= ed):
            continue
        target = (c.get("target_city_county") or "").strip()
        if not _city_matches_target(store_city, target):
            continue
        matches.append(c)
    if not matches:
        return DEFAULT_CAMPAIGN_ID
    matches.sort(
        key=lambda x: (
            int(x.get("priority") or 100),
            0 if (x.get("target_city_county") or "").strip() else 1,
            int(x.get("campaign_id") or 0),
        )
    )
    return int(matches[0].get("campaign_id") or DEFAULT_CAMPAIGN_ID)


class CampaignItem(BaseModel):
    campaignId: int
    name: str = "DEFAULT"
    active: bool = True
    targetCityCounty: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    projectType: Optional[ProjectType] = None
    priority: int = 100


class ActiveCampaignsResponse(BaseModel):
    defaultCampaignId: int
    items: List[CampaignItem] = Field(default_factory=list)


@app.get(
    "/api/v1/campaigns/active",
    response_model=ActiveCampaignsResponse,
    summary="활성 캠페인 조회(확장 포인트)",
    description="활성 캠페인 목록. FE는 보통 campaignId를 전송하지 않고(내부용), 필요 시 화면 표시/선택을 위해 조회할 수 있습니다.",
    tags=["FE - Campaigns"],
)
async def get_active_campaigns(db: Session = Depends(get_db)):
    rows = _fetch_active_campaign_rows(db)
    if not rows:
        return ActiveCampaignsResponse(
            defaultCampaignId=DEFAULT_CAMPAIGN_ID,
            items=[CampaignItem(campaignId=DEFAULT_CAMPAIGN_ID, name="DEFAULT", active=True)],
        )
    items: List[CampaignItem] = []
    for r in rows:
        sd = _parse_date_any(r.get("start_date"))
        ed = _parse_date_any(r.get("end_date"))
        items.append(
            CampaignItem(
                campaignId=int(r.get("campaign_id")),
                name=(r.get("campaign_name") or "DEFAULT"),
                active=bool(r.get("is_active", True)),
                targetCityCounty=(r.get("target_city_county") or None),
                startDate=sd.isoformat() if sd else None,
                endDate=ed.isoformat() if ed else None,
                projectType=ProjectType(r["project_type"]) if (r.get("project_type") in ("STAY", "TOUR")) else None,
                priority=int(r.get("priority") or 100),
            )
        )
    items.sort(key=lambda x: (x.priority, x.campaignId))
    return ActiveCampaignsResponse(defaultCampaignId=DEFAULT_CAMPAIGN_ID, items=items)


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


@app.get("/api/health", summary="헬스 체크 (S3·DB·콜백 URL 확인)", tags=["Ops"])
async def health_check():
    """S3 버킷 접근, DB 연결·테이블 존재 여부, 콜백 URL 적용 여부를 확인합니다. 배포/프록시에서 사용."""
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
    # 콜백 URL 적용 여부만 노출 (URL 값은 보안상 반환하지 않음)
    ocr_callback_configured = bool(OCR_RESULT_CALLBACK_URL)
    return {"status": "ok", "s3": "ok", "db": "ok", "ocr_callback_configured": ocr_callback_configured}


@app.post(
    "/api/v1/receipts/presigned-url",
    response_model=PresignedUrlResponse,
    tags=["FE - Step 1: Presigned URL"],
)
async def get_presigned_url(
    fileName: str,
    contentType: str,
    userUuid: str,
    type: ProjectType,
    receiptId: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    1단계: 고객 영수증 업로드용 Presigned URL 발급 (10분 유효).
    - receiptId를 전달하면 동일 신청(합산형)으로 이미지를 계속 추가할 수 있음.
    - receiptId 미전달 시 새 신청을 생성.
    """
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
            # receiptId 재사용은 "같은 신청(같은 type)"에 한해서만 허용 (STAY↔TOUR 엉킴 방지)
            if (existing.project_type or "").strip() and existing.project_type != type:
                raise HTTPException(status_code=409, detail="receiptId type mismatch")
            # campaign_id는 presigned 최초 생성 시 서버가 고정. 기존 submission에서는 덮어쓰지 않는다.
        else:
            campaign_id = _resolve_campaign_id_for_presigned(db, userUuid, type)
            db.add(
                Submission(
                    submission_id=receipt_id,
                    user_uuid=userUuid,
                    project_type=type,
                    campaign_id=campaign_id,
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


@app.post(
    "/api/v1/receipts/upload",
    response_model=PresignedUrlResponse,
    tags=["FE - Step 1b: Upload (fallback)"],
)
async def upload_receipt_via_api(
    file: UploadFile = File(...),
    userUuid: str = Form(...),
    type: ProjectType = Form(...),
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


async def _submit_receipt_common(req: CompleteRequest, background_tasks: BackgroundTasks, db: Session):
    """
    3단계 공통 처리: 비동기 분석 시작. 1건 신청 = 1 receiptId = complete 1회.
    동일 receiptId에 대한 동시 Complete 요청 시 한 건만 PROCESSING으로 전환되도록 원자적 업데이트 사용.
    """
    submission = db.query(Submission).filter(Submission.submission_id == req.receiptId).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    if submission.user_uuid != req.userUuid:
        raise HTTPException(status_code=403, detail="receiptId owner mismatch")

    # receiptId는 생성 시 type이 고정됨. 다른 type으로 complete 호출 시 엉킴 방지.
    if (submission.project_type or "").strip() and submission.project_type != req.type:
        raise HTTPException(status_code=409, detail="receiptId type mismatch")

    # campaignId는 서버가 submission 생성 시 고정한다.
    if req.campaignId is not None and submission.campaign_id and submission.campaign_id != req.campaignId:
        raise HTTPException(status_code=409, detail="campaignId mismatch")
    if not submission.campaign_id:
        submission.campaign_id = _resolve_campaign_id_for_presigned(db, submission.user_uuid, req.type)

    if submission.status in ("FIT", "UNFIT", "ERROR"):
        raise HTTPException(status_code=409, detail="Submission already completed")

    if submission.status in ("PROCESSING", "VERIFYING"):
        return {"status": submission.status, "receiptId": req.receiptId}

    # 원자적 전환: PENDING → PROCESSING. 동시 요청 시 한 건만 성공하여 중복 백그라운드 태스크 방지.
    if not submission.campaign_id:
        submission.campaign_id = _resolve_campaign_id_for_presigned(db, submission.user_uuid, req.type)
    snap = req.data.model_dump() if req.data is not None else None
    values = {"status": "PROCESSING", "user_input_snapshot": snap}
    if submission.campaign_id:
        values["campaign_id"] = submission.campaign_id
    stmt = (
        update(Submission)
        .where(
            Submission.submission_id == req.receiptId,
            Submission.status == "PENDING",
        )
        .values(**values)
    )
    result = db.execute(stmt)
    db.commit()
    if result.rowcount == 0:
        # 이미 다른 요청이 PROCESSING/VERIFYING으로 전환함 → 현재 상태 반환
        refetched = db.query(Submission).filter(Submission.submission_id == req.receiptId).first()
        return {"status": (refetched.status if refetched else "PROCESSING"), "receiptId": req.receiptId}

    background_tasks.add_task(analyze_receipt_task, req)
    return {"status": "PROCESSING", "receiptId": req.receiptId}


@app.post(
    "/api/v1/receipts/complete",
    response_model=CompleteResponse,
    summary="검증 완료 요청",
    description="receiptId 기준 1회 호출. documents 필수, data(방식2: items[]) 선택. "
    "data.items[]는 documents와 동일 순서·길이. 분석 완료 시 OCR_RESULT_CALLBACK_URL이 설정된 경우 FE로 결과 POST(재시도 없음).",
    tags=["FE - Step 3: Complete"],
)
async def submit_receipt(req: CompleteRequestV2, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    FE 연동. documents 필수, data(방식2: items[]) 선택. data 있으면 user_input_snapshot 저장·OCR 비교에 사용.
    """
    v1_req = CompleteRequest(
        receiptId=req.receiptId,
        userUuid=req.userUuid,
        type=req.type,
        campaignId=None,
        documents=req.documents,
        data=req.data,
    )
    return await _submit_receipt_common(v1_req, background_tasks, db)


@app.post(
    "/api/v1/receipts/complete-legacy",
    response_model=CompleteResponse,
    include_in_schema=False,
)
async def submit_receipt_legacy(
    req: CompleteRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """(Legacy) 과거 클라이언트 호환용. 신규 FE 연동에서는 사용하지 않는다."""
    return await _submit_receipt_common(req, background_tasks, db)

class ExtractedData(BaseModel):
    store_name: Optional[str] = Field(None, description="상호명")
    amount: int = Field(0, description="인식된 금액")
    pay_date: Optional[str] = Field(None, description="결제일자")
    address: Optional[str] = Field(None, description="상점 주소")
    card_num: str = Field("1000", description="카드번호 앞 4자리. 현금=0000, 카드번호 없음/****=1000, 유효 시 마지막 4자리")


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
    # FE 폴링 가이드
    shouldPoll: bool = Field(False, description="true면 FE가 같은 status API를 재호출")
    recommendedPollIntervalMs: Optional[int] = Field(
        None,
        description="권장 폴링 주기(ms). shouldPoll=true일 때만 의미",
    )
    reviewRequired: bool = Field(False, description="관리자/담당자 수동 검토 필요 여부")
    statusStage: str = Field(
        "DONE",
        description="AUTO_PROCESSING | MANUAL_REVIEW | DONE",
    )

def _parse_city_county_from_address(address: Optional[str]) -> Optional[str]:
    """주소에서 시군 구 추출. '강원특별자치도 춘천시 중앙로 123' -> '춘천시'."""
    if not address or not isinstance(address, str):
        return None
    parts = address.strip().split()
    return parts[1] if len(parts) >= 2 else None


def _normalize_unknown_store_policy(raw: Optional[str]) -> str:
    s = (raw or "").strip().upper()
    if s in ("PENDING_NEW", "AUTO_REGISTER"):
        return s
    return "AUTO_REGISTER"


def _get_judgment_rule_config(db: Session) -> JudgmentRuleConfig:
    """판정 규칙 싱글톤 로드. 없으면 기본행(id=1) 생성."""
    cfg = db.query(JudgmentRuleConfig).filter(JudgmentRuleConfig.id == 1).first()
    if cfg:
        return cfg
    cfg = JudgmentRuleConfig(
        id=1,
        unknown_store_policy="AUTO_REGISTER",
        auto_register_threshold=0.90,
        enable_gemini_classifier=True,
        min_amount_stay=60000,
        min_amount_tour=50000,
        orphan_object_days=1,
        expired_candidate_days=1,
        orphan_object_minutes=1440,
        expired_candidate_minutes=1440,
        verifying_timeout_minutes=0,
        verifying_timeout_action="UNFIT",
        updated_at=datetime.utcnow(),
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


def _cfg_orphan_minutes(cfg: JudgmentRuleConfig) -> int:
    """고아 객체 유효기간(분). 분 컬럼 우선, 없으면 일*1440."""
    m = getattr(cfg, "orphan_object_minutes", None)
    if m is not None and m > 0:
        return int(m)
    return (getattr(cfg, "orphan_object_days", None) or 1) * 1440


def _cfg_expired_minutes(cfg: JudgmentRuleConfig) -> int:
    """만료 후보 유효기간(분). 분 컬럼 우선, 없으면 일*1440."""
    m = getattr(cfg, "expired_candidate_minutes", None)
    if m is not None and m > 0:
        return int(m)
    return (getattr(cfg, "expired_candidate_days", None) or 1) * 1440


def require_admin(
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
    x_admin_actor: Optional[str] = Header(None, alias="X-Admin-Actor"),
) -> str:
    """
    관리자 API 접근 가드(선택).
    - ADMIN_API_KEY 환경변수가 설정된 경우에만 X-Admin-Key를 검증한다.
    - actor는 감사로그용 식별자(없으면 'admin').
    """
    if ADMIN_API_KEY and (x_admin_key or "").strip() != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized admin request")
    return (x_admin_actor or "admin").strip() or "admin"


def _dict_for_jsonb(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """JSONB 저장용: date/datetime을 ISO 문자열로 변환해 직렬화 오류 방지."""
    if d is None:
        return None
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if v is None:
            out[k] = None
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, dict):
            out[k] = _dict_for_jsonb(v)
        elif isinstance(v, (list, tuple)):
            out[k] = [
                (x.isoformat() if hasattr(x, "isoformat") else _dict_for_jsonb(x) if isinstance(x, dict) else x)
                for x in v
            ]
        else:
            out[k] = v
    return out


def _audit_log(
    db: Session,
    actor: str,
    action: str,
    target_type: str,
    target_id: str,
    before_json: Optional[Dict[str, Any]] = None,
    after_json: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        db.add(
            AdminAuditLog(
                actor=actor,
                action=action,
                target_type=target_type,
                target_id=target_id,
                before_json=_dict_for_jsonb(before_json),
                after_json=_dict_for_jsonb(after_json),
                meta=_dict_for_jsonb(meta),
            )
        )
    except Exception:
        # 감사로그 실패는 운영에 치명적이지 않게 처리(본 트랜잭션은 유지)
        pass


def _sanitize_receipt_id(raw: str) -> str:
    """FE/프록시에서 잘못 붙은 문자가 있을 수 있음 (예: 'uuid HTTP/1.1\" 404...'). UUID만 추출."""
    if not raw:
        return ""
    s = raw.strip()
    match = re.match(r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", s)
    return match.group(1) if match else s.split()[0] if s.split() else s


def _polling_hint_by_status(status: Optional[str]) -> Tuple[bool, Optional[int], bool, str]:
    """
    FE 폴링 정책 가이드:
    - AUTO_PROCESSING: OCR/자동검증 중 → 빠른 폴링(2s)
    - MANUAL_REVIEW: 관리자 검토 대기 → 느린 폴링(30s)
    - DONE: 최종 완료/종결 상태 → 폴링 중지
    """
    s = (status or "").strip()
    if s in ("PROCESSING", "VERIFYING"):
        return True, 2000, False, "AUTO_PROCESSING"
    if s in ("PENDING_NEW", "PENDING_VERIFICATION"):
        return True, 30000, True, "MANUAL_REVIEW"
    return False, None, False, "DONE"


def _build_status_payload(submission: Submission, item_rows: List[Any]) -> Dict[str, Any]:
    """
    콜백 전송용 payload 생성.
    - GET status 응답과 거의 동일하되, 콜백에서는 대용량 필드(예: items[].ocr_raw)를 제외해 전송량을 줄인다.
    """
    first_item = item_rows[0] if item_rows else None
    address = None
    card_prefix = None
    if first_item:
        address = (first_item.address or first_item.location or first_item.store_name or "").strip() or None
        card_prefix = first_item.card_num or None
    if submission.status in ("VERIFYING", "PROCESSING") and card_prefix in (CARD_NUM_CASH, CARD_NUM_NO_CARD):
        card_prefix = None
    audit_trail_raw = (submission.audit_trail or submission.audit_log or "")
    audit_trail_truncated = False
    if OCR_CALLBACK_MAX_AUDIT_TRAIL_CHARS > 0 and len(audit_trail_raw) > OCR_CALLBACK_MAX_AUDIT_TRAIL_CHARS:
        audit_trail_raw = audit_trail_raw[: OCR_CALLBACK_MAX_AUDIT_TRAIL_CHARS - 1] + "…"
        audit_trail_truncated = True

    item_details: List[Dict[str, Any]] = []
    error_message_truncated_count = 0
    for it in item_rows:
        extracted = None
        if it.status != "ERROR":
            extracted = {
                "store_name": it.store_name,
                "amount": it.amount or 0,
                "pay_date": it.pay_date,
                "address": it.address,
                "card_num": it.card_num or CARD_NUM_NO_CARD,
            }
        err_msg = it.error_message
        if (
            err_msg
            and OCR_CALLBACK_MAX_ERROR_MESSAGE_CHARS > 0
            and len(err_msg) > OCR_CALLBACK_MAX_ERROR_MESSAGE_CHARS
        ):
            err_msg = err_msg[: OCR_CALLBACK_MAX_ERROR_MESSAGE_CHARS - 1] + "…"
            error_message_truncated_count += 1
        item_details.append({
            "item_id": str(it.item_id),
            "status": it.status or "PENDING",
            "error_code": _normalize_error_code(it.error_code),
            "error_message": err_msg,
            "extracted_data": extracted,
            "image_url": it.image_key or "",
            # 콜백 최적화: ocr_raw는 매우 크므로 콜백에서는 제외 (GET status에서만 제공)
        })
    should_poll, poll_interval_ms, review_required, status_stage = _polling_hint_by_status(submission.status)
    resp = StatusResponse(
        submission_id=submission.submission_id,
        project_type=submission.project_type,
        overall_status=submission.status,
        total_amount=submission.total_amount or 0,
        global_fail_reason=submission.global_fail_reason or submission.fail_reason,
        items=item_details,
        audit_trail=audit_trail_raw,
        status=submission.status,
        amount=submission.total_amount or 0,
        failReason=submission.fail_reason,
        rewardAmount=30000 if submission.project_type == "STAY" and submission.status == "FIT" else 10000 if submission.status == "FIT" else 0,
        address=address,
        cardPrefix=card_prefix,
        shouldPoll=should_poll,
        recommendedPollIntervalMs=poll_interval_ms,
        reviewRequired=review_required,
        statusStage=status_stage,
    )
    payload = resp.model_dump(mode="json")
    payload["payloadMeta"] = {
        "auditTrailTruncated": audit_trail_truncated,
        "errorMessageTruncatedCount": error_message_truncated_count,
        "generatedAt": datetime.utcnow().isoformat(),
    }
    return payload


async def _send_result_callback(
    receipt_id: str,
    payload: Dict[str, Any],
    target_url: Optional[str] = None,
    *,
    purpose: str = "auto",  # auto | resend
    actor: str = "system",
) -> Dict[str, Any]:
    """분석 완료 시 FE 지정 URL로 결과 POST. 재시도 없음. 성공/실패를 로그 + AdminAuditLog에 기록."""
    url = (target_url or "").strip() if target_url else None
    url = url or OCR_RESULT_CALLBACK_URL
    if not url:
        return {"skipped": True, "reason": "OCR_RESULT_CALLBACK_URL is not set"}
    payload_with_id = {
        "schemaVersion": OCR_CALLBACK_SCHEMA_VERSION,
        "receiptId": receipt_id,
        **payload,
    }
    try:
        started = time.time()
        async with httpx.AsyncClient(timeout=OCR_CALLBACK_TIMEOUT_SEC) as client:
            r = await client.post(
                url,
                json=payload_with_id,
                headers={"Content-Type": "application/json"},
            )
            elapsed_ms = int(round((time.time() - started) * 1000.0))
            ok = r.status_code < 400
            if ok:
                logger.info(
                    "OCR result callback sent: receiptId=%s purpose=%s url=%s status=%s elapsedMs=%s",
                    receipt_id,
                    purpose,
                    url,
                    r.status_code,
                    elapsed_ms,
                )
            else:
                logger.warning(
                    "OCR result callback failed: receiptId=%s purpose=%s url=%s status=%s elapsedMs=%s body=%s",
                    receipt_id,
                    purpose,
                    url,
                    r.status_code,
                    elapsed_ms,
                    (r.text or "")[:200],
                )

            # 콜백 송출 결과를 DB에 남겨, Coolify/관리자 화면에서 추적 가능하게 한다.
            try:
                db2 = SessionLocal()
                _audit_log(
                    db2,
                    actor=actor,
                    action="CALLBACK_SEND",
                    target_type="submission",
                    target_id=receipt_id,
                    meta={
                        "purpose": purpose,
                        "url": url,
                        "status": int(r.status_code),
                        "ok": bool(ok),
                        "elapsed_ms": elapsed_ms,
                        "response_body": (None if ok else (r.text or "")[:200]),
                    },
                )
                db2.commit()
            except Exception:
                pass
            finally:
                try:
                    db2.close()  # type: ignore[name-defined]
                except Exception:
                    pass
            return {
                "receiptId": receipt_id,
                "url": url,
                "purpose": purpose,
                "ok": bool(ok),
                "status": int(r.status_code),
                "elapsed_ms": elapsed_ms,
            }
    except Exception as e:
        logger.warning(
            "OCR result callback error (no retry): receiptId=%s purpose=%s url=%s err=%s",
            receipt_id,
            purpose,
            url,
            e,
        )
        try:
            db2 = SessionLocal()
            _audit_log(
                db2,
                actor=actor,
                action="CALLBACK_SEND",
                target_type="submission",
                target_id=receipt_id,
                meta={"purpose": purpose, "url": url, "ok": False, "error": str(e)[:200]},
            )
            db2.commit()
        except Exception:
            pass
        finally:
            try:
                db2.close()  # type: ignore[name-defined]
            except Exception:
                pass
        return {"receiptId": receipt_id, "url": url, "purpose": purpose, "ok": False, "error": str(e)[:200]}


async def _process_verifying_timeout_run(db: Session, actor: str = "system") -> Tuple[int, List[str]]:
    """
    VERIFYING/PENDING_VERIFICATION 상태로 설정된 지 verifying_timeout_minutes를 초과한 건을
    UNFIT 또는 ERROR로 변경하고 FE 콜백 URL로 전송. 기관 정책(판정 규칙)에 따라 동작.
    """
    cfg = _get_judgment_rule_config(db)
    timeout_min = int(getattr(cfg, "verifying_timeout_minutes", None) or 0)
    if timeout_min <= 0:
        return 0, []
    action = (getattr(cfg, "verifying_timeout_action", None) or "UNFIT").strip().upper()
    if action not in ("UNFIT", "ERROR"):
        action = "UNFIT"
    cutoff_naive = datetime.utcnow() - timedelta(minutes=timeout_min)
    overdue = (
        db.query(Submission)
        .filter(
            Submission.status.in_(["VERIFYING", "PENDING_VERIFICATION"]),
            func.coalesce(Submission.updated_at, Submission.created_at) < cutoff_naive,
        )
        .all()
    )
    if not overdue:
        return 0, []
    processed: List[str] = []
    reason = "VERIFYING_TIMEOUT (대기 시간 초과)"
    for sub in overdue:
        try:
            sub.status = action
            sub.fail_reason = reason
            sub.global_fail_reason = reason
            sub.updated_at = datetime.utcnow()
            db.commit()
            item_rows = (
                db.query(ReceiptItem)
                .filter(ReceiptItem.submission_id == sub.submission_id)
                .order_by(ReceiptItem.seq_no.asc())
                .all()
            )
            payload = _build_status_payload(sub, item_rows)
            await _send_result_callback(sub.submission_id, payload, purpose="verifying_timeout", actor=actor)
            processed.append(sub.submission_id)
        except Exception as e:
            logger.warning("verifying_timeout process failed for %s: %s", sub.submission_id, e)
            db.rollback()
    return len(processed), processed


def _safe_process_status(raw: Optional[str]) -> str:
    """DB 값이 ProcessStatus enum에 없으면 PENDING 반환 (직렬화 500 방지)."""
    if not raw or not isinstance(raw, str):
        return "PENDING"
    s = raw.strip().upper()
    if s in (e.value for e in ProcessStatus):
        return s
    return "PENDING"


def _safe_pay_date_str(raw: Any) -> Optional[str]:
    """날짜/문자열을 응답용 문자열로. None이면 None, date/datetime이면 isoformat."""
    if raw is None:
        return None
    if hasattr(raw, "isoformat"):
        return raw.isoformat()
    return str(raw).strip() or None


@app.get(
    "/api/v1/receipts/{receiptId}/status",
    response_model=StatusResponse,
    responses={404: {"description": "Receipt not found"}},
    summary="결과 조회(폴링/스케줄러 복구)",
    description="receiptId 단위 최종 판정. 동일 receiptId에 대해 언제든 반복 호출 가능(FE 스케줄러 누락 복구용). "
    "콜백과 동일한 JSON 구조(콜백 시 Body에 receiptId 추가하여 전송).",
    tags=["FE - Step 6: Status"],
)
async def get_status(receiptId: str, db: Session = Depends(get_db)):
    """4단계: 최종 결과 조회. receiptId 단위 적합/부적합, DB 기준 최신값 반환."""
    receipt_id = _sanitize_receipt_id(receiptId)
    submission = db.query(Submission).filter(Submission.submission_id == receipt_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    db.refresh(submission)
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
    # VERIFYING/PROCESSING 중 placeholder만 있을 땐 카드 미확정으로 null 반환 (0000/1000 노출 방지)
    if submission.status in ("VERIFYING", "PROCESSING") and card_prefix in (CARD_NUM_CASH, CARD_NUM_NO_CARD):
        card_prefix = None
    item_details: List[ReceiptItemSchema] = []
    for it in item_rows:
        extracted = None
        if it.status != "ERROR":
            extracted = ExtractedData(
                store_name=it.store_name,
                amount=int(it.amount) if it.amount is not None else 0,
                pay_date=_safe_pay_date_str(it.pay_date),
                address=it.address,
                card_num=it.card_num or CARD_NUM_NO_CARD,
            )
        item_details.append(
            ReceiptItemSchema(
                item_id=str(it.item_id) if it.item_id is not None else "",
                status=_safe_process_status(it.status),
                error_code=_normalize_error_code(it.error_code),
                error_message=it.error_message,
                extracted_data=extracted,
                image_url=(it.image_key or "").strip() or "",
                ocr_raw=it.ocr_raw,
            )
        )
    sub_status = _safe_process_status(submission.status)
    should_poll, poll_interval_ms, review_required, status_stage = _polling_hint_by_status(submission.status)
    total = submission.total_amount if submission.total_amount is not None else 0
    return StatusResponse(
        submission_id=submission.submission_id,
        project_type=submission.project_type or "STAY",
        overall_status=sub_status,
        total_amount=total,
        global_fail_reason=submission.global_fail_reason or submission.fail_reason,
        items=item_details,
        audit_trail=(submission.audit_trail or submission.audit_log or ""),
        status=sub_status,
        amount=total,
        failReason=submission.fail_reason,
        rewardAmount=30000 if submission.project_type == "STAY" and sub_status == "FIT" else 10000 if sub_status == "FIT" else 0,
        address=address,
        cardPrefix=card_prefix,
        shouldPoll=should_poll,
        recommendedPollIntervalMs=poll_interval_ms,
        reviewRequired=review_required,
        statusStage=status_stage,
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


# 5-0. 캠페인 관리/조회 API
class AdminCampaignItem(BaseModel):
    campaignId: int
    name: Optional[str] = None
    active: bool = True
    targetCityCounty: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    projectType: Optional[ProjectType] = None
    priority: int = 100
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class AdminCampaignListResponse(BaseModel):
    total: int
    items: List[AdminCampaignItem] = Field(default_factory=list)


class AdminCampaignUpsertRequest(BaseModel):
    name: str
    active: bool = True
    targetCityCounty: Optional[str] = None
    startDate: Optional[str] = None  # YYYY-MM-DD
    endDate: Optional[str] = None    # YYYY-MM-DD
    projectType: Optional[ProjectType] = None
    priority: int = 100


def _admin_fetch_campaign_rows(db: Session) -> List[Dict[str, Any]]:
    try:
        rows = db.execute(
            sql_text(
                "SELECT campaign_id, campaign_name, is_active, target_city_county, start_date, end_date, created_at, "
                "COALESCE(priority, 100) AS priority, project_type, updated_at "
                "FROM campaigns ORDER BY COALESCE(priority, 100) ASC, campaign_id ASC"
            )
        ).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        rows = db.execute(
            sql_text(
                "SELECT campaign_id, campaign_name, is_active, target_city_county, start_date, end_date, created_at "
                "FROM campaigns ORDER BY campaign_id ASC"
            )
        ).mappings().all()
        items: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["priority"] = 100
            d["project_type"] = None
            d["updated_at"] = None
            items.append(d)
        return items


@app.get(
    "/api/v1/admin/campaigns",
    response_model=AdminCampaignListResponse,
    summary="캠페인 목록 조회(관리자)",
    tags=["Admin - Campaigns"],
)
async def admin_list_campaigns(db: Session = Depends(get_db), actor: str = Depends(require_admin)):
    rows = _admin_fetch_campaign_rows(db)
    items: List[AdminCampaignItem] = []
    for r in rows:
        sd = _parse_date_any(r.get("start_date"))
        ed = _parse_date_any(r.get("end_date"))
        items.append(
            AdminCampaignItem(
                campaignId=int(r.get("campaign_id")),
                name=r.get("campaign_name"),
                active=bool(r.get("is_active", True)),
                targetCityCounty=(r.get("target_city_county") or None),
                startDate=sd.isoformat() if sd else None,
                endDate=ed.isoformat() if ed else None,
                projectType=ProjectType(r["project_type"]) if (r.get("project_type") in ("STAY", "TOUR")) else None,
                priority=int(r.get("priority") or 100),
                createdAt=(r.get("created_at").isoformat() if isinstance(r.get("created_at"), datetime) else None),
                updatedAt=(r.get("updated_at").isoformat() if isinstance(r.get("updated_at"), datetime) else None),
            )
        )
    return AdminCampaignListResponse(total=len(items), items=items)


@app.post(
    "/api/v1/admin/campaigns",
    response_model=AdminCampaignItem,
    summary="캠페인 생성(관리자)",
    tags=["Admin - Campaigns"],
)
async def admin_create_campaign(
    body: AdminCampaignUpsertRequest, db: Session = Depends(get_db), actor: str = Depends(require_admin)
):
    sd = _parse_date_any(body.startDate)
    ed = _parse_date_any(body.endDate)
    target = (body.targetCityCounty or "").strip() or None
    pt = body.projectType.value if body.projectType else None
    pr = int(body.priority or 100)

    # 기본 컬럼으로 먼저 생성
    res = db.execute(
        sql_text(
            "INSERT INTO campaigns (campaign_name, is_active, target_city_county, start_date, end_date, created_at) "
            "VALUES (:name, :active, :target, :sd, :ed, NOW()) "
            "RETURNING campaign_id"
        ),
        {"name": body.name.strip(), "active": bool(body.active), "target": target, "sd": sd, "ed": ed},
    ).fetchone()
    cid = int(res[0]) if res else 0
    # 확장 컬럼이 있으면 업데이트
    try:
        db.execute(
            sql_text(
                "UPDATE campaigns SET priority=:pr, project_type=:pt, updated_at=NOW() WHERE campaign_id=:cid"
            ),
            {"pr": pr, "pt": pt, "cid": cid},
        )
    except Exception:
        pass
    db.commit()

    _audit_log(
        db,
        actor=actor,
        action="CAMPAIGN_CREATE",
        target_type="campaign",
        target_id=str(cid),
        after_json={
            "campaignId": cid,
            "name": body.name,
            "active": body.active,
            "targetCityCounty": target,
            "startDate": body.startDate,
            "endDate": body.endDate,
            "projectType": pt,
            "priority": pr,
        },
    )
    db.commit()
    return AdminCampaignItem(
        campaignId=cid,
        name=body.name,
        active=bool(body.active),
        targetCityCounty=target,
        startDate=sd.isoformat() if sd else None,
        endDate=ed.isoformat() if ed else None,
        projectType=body.projectType,
        priority=pr,
    )


@app.put(
    "/api/v1/admin/campaigns/{campaignId}",
    response_model=AdminCampaignItem,
    summary="캠페인 수정(관리자)",
    description="campaignId는 경로에 숫자로 지정. 요청 본문에 name(필수), active, startDate, endDate, projectType, priority 등 전송.",
    tags=["Admin - Campaigns"],
)
async def admin_update_campaign(
    campaignId: int,
    body: AdminCampaignUpsertRequest = Body(
        ...,
        example={
            "name": "캠페인명",
            "active": True,
            "targetCityCounty": None,
            "startDate": None,
            "endDate": None,
            "projectType": "STAY",
            "priority": 100,
        },
    ),
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    # before snapshot (JSONB 저장용 직렬화 가능 dict로 감사 로그에 전달)
    before_rows = _admin_fetch_campaign_rows(db)
    before = next((r for r in before_rows if int(r.get("campaign_id")) == int(campaignId)), None)
    if not before:
        raise HTTPException(status_code=404, detail="Campaign not found")

    sd = _parse_date_any(body.startDate)
    ed = _parse_date_any(body.endDate)
    target = (body.targetCityCounty or "").strip() or None
    pt = body.projectType.value if body.projectType else None
    pr = int(body.priority or 100)

    db.execute(
        sql_text(
            "UPDATE campaigns SET campaign_name=:name, is_active=:active, target_city_county=:target, "
            "start_date=:sd, end_date=:ed WHERE campaign_id=:cid"
        ),
        {
            "name": body.name.strip(),
            "active": bool(body.active),
            "target": target,
            "sd": sd,
            "ed": ed,
            "cid": int(campaignId),
        },
    )
    try:
        db.execute(
            sql_text(
                "UPDATE campaigns SET priority=:pr, project_type=:pt, updated_at=NOW() WHERE campaign_id=:cid"
            ),
            {"pr": pr, "pt": pt, "cid": int(campaignId)},
        )
    except Exception:
        pass
    db.commit()

    _audit_log(
        db,
        actor=actor,
        action="CAMPAIGN_UPDATE",
        target_type="campaign",
        target_id=str(campaignId),
        before_json=before,
        after_json={
            "campaignId": int(campaignId),
            "name": body.name,
            "active": body.active,
            "targetCityCounty": target,
            "startDate": body.startDate,
            "endDate": body.endDate,
            "projectType": pt,
            "priority": pr,
        },
    )
    db.commit()

    return AdminCampaignItem(
        campaignId=int(campaignId),
        name=body.name,
        active=bool(body.active),
        targetCityCounty=target,
        startDate=sd.isoformat() if sd else None,
        endDate=ed.isoformat() if ed else None,
        projectType=body.projectType,
        priority=pr,
    )


# 5-1. 판정 규칙 관리 API (관리자)
ValidityUnit = Literal["days", "hours", "minutes"]
VERIFYING_TIMEOUT_ACTION = Literal["UNFIT", "ERROR"]
MAX_VALIDITY_MINUTES = 365 * 24 * 60  # 525600


def _minutes_from_value_unit(value: int, unit: str) -> int:
    """value + unit( days | hours | minutes ) → 분."""
    if unit == "days":
        return value * 24 * 60
    if unit == "hours":
        return value * 60
    return value  # minutes


class JudgmentRuleConfigResponse(BaseModel):
    unknown_store_policy: str = Field(..., description="AUTO_REGISTER(기본, 자동 상점추가·데이터 자산화) | PENDING_NEW(신규상점 검수 대기)")
    auto_register_threshold: float = Field(..., description="0.0~1.0")
    enable_gemini_classifier: bool = Field(..., description="신규 상점 분류 시 Gemini 사용 여부")
    min_amount_stay: int = Field(..., description="STAY 최소 금액")
    min_amount_tour: int = Field(..., description="TOUR 최소 금액")
    orphan_object_days: int = Field(1, description="고아 객체 유효(일). 하위호환, orphan_object_minutes/1440")
    expired_candidate_days: int = Field(1, description="만료 후보 유효(일). 하위호환")
    orphan_object_minutes: int = Field(1440, description="고아 객체 유효기간(분). 일/시간/분 단위 설정 가능")
    expired_candidate_minutes: int = Field(1440, description="만료 후보 유효기간(분)")
    verifying_timeout_minutes: int = Field(0, description="VERIFYING 대기 허용(분). 0=비활성, 초과 시 action 적용 후 콜백")
    verifying_timeout_action: str = Field("UNFIT", description="대기 초과 시 적용: UNFIT | ERROR")
    updated_at: Optional[str] = None


class JudgmentRuleConfigUpdateRequest(BaseModel):
    unknown_store_policy: Optional[str] = Field(None, description="AUTO_REGISTER(기본) | PENDING_NEW")
    auto_register_threshold: Optional[float] = Field(None, description="0.0~1.0")
    enable_gemini_classifier: Optional[bool] = None
    min_amount_stay: Optional[int] = None
    min_amount_tour: Optional[int] = None
    orphan_object_days: Optional[int] = Field(None, ge=1, le=365, description="고아 객체 유효(일). 하위호환")
    expired_candidate_days: Optional[int] = Field(None, ge=1, le=365, description="만료 후보 유효(일). 하위호환")
    orphan_object_minutes: Optional[int] = Field(None, ge=1, le=MAX_VALIDITY_MINUTES, description="고아 객체 유효(분)")
    expired_candidate_minutes: Optional[int] = Field(None, ge=1, le=MAX_VALIDITY_MINUTES, description="만료 후보 유효(분)")
    orphan_object_value: Optional[int] = Field(None, ge=1, description="value+unit으로 설정 시 값")
    orphan_object_unit: Optional[ValidityUnit] = Field(None, description="days | hours | minutes")
    expired_candidate_value: Optional[int] = Field(None, ge=1, description="value+unit으로 설정 시 값")
    expired_candidate_unit: Optional[ValidityUnit] = Field(None, description="days | hours | minutes")
    verifying_timeout_minutes: Optional[int] = Field(None, ge=0, le=MAX_VALIDITY_MINUTES, description="VERIFYING 대기(분). 0=비활성")
    verifying_timeout_action: Optional[VERIFYING_TIMEOUT_ACTION] = Field(None, description="UNFIT | ERROR")


@app.get(
    "/api/v1/admin/rules/judgment",
    response_model=JudgmentRuleConfigResponse,
    summary="판정 규칙 조회",
    tags=["Admin - Rules"],
)
async def get_judgment_rule_config(db: Session = Depends(get_db), actor: str = Depends(require_admin)):
    cfg = _get_judgment_rule_config(db)
    o_min = _cfg_orphan_minutes(cfg)
    e_min = _cfg_expired_minutes(cfg)
    return JudgmentRuleConfigResponse(
        unknown_store_policy=_normalize_unknown_store_policy(cfg.unknown_store_policy),
        auto_register_threshold=float(cfg.auto_register_threshold or 0.90),
        enable_gemini_classifier=bool(cfg.enable_gemini_classifier),
        min_amount_stay=int(cfg.min_amount_stay or 60000),
        min_amount_tour=int(cfg.min_amount_tour or 50000),
        orphan_object_days=o_min // 1440,
        expired_candidate_days=e_min // 1440,
        orphan_object_minutes=o_min,
        expired_candidate_minutes=e_min,
        verifying_timeout_minutes=int(getattr(cfg, "verifying_timeout_minutes", None) or 0),
        verifying_timeout_action=(getattr(cfg, "verifying_timeout_action", None) or "UNFIT"),
        updated_at=cfg.updated_at.isoformat() if cfg.updated_at else None,
    )


@app.put(
    "/api/v1/admin/rules/judgment",
    response_model=JudgmentRuleConfigResponse,
    summary="판정 규칙 수정",
    tags=["Admin - Rules"],
)
async def update_judgment_rule_config(
    body: JudgmentRuleConfigUpdateRequest, db: Session = Depends(get_db), actor: str = Depends(require_admin)
):
    cfg = _get_judgment_rule_config(db)
    o_min = _cfg_orphan_minutes(cfg)
    e_min = _cfg_expired_minutes(cfg)
    before = {
        "unknown_store_policy": cfg.unknown_store_policy,
        "auto_register_threshold": float(cfg.auto_register_threshold or 0.90),
        "enable_gemini_classifier": bool(cfg.enable_gemini_classifier),
        "min_amount_stay": int(cfg.min_amount_stay or 60000),
        "min_amount_tour": int(cfg.min_amount_tour or 50000),
        "orphan_object_days": o_min // 1440,
        "expired_candidate_days": e_min // 1440,
        "orphan_object_minutes": o_min,
        "expired_candidate_minutes": e_min,
        "verifying_timeout_minutes": int(getattr(cfg, "verifying_timeout_minutes", None) or 0),
        "verifying_timeout_action": getattr(cfg, "verifying_timeout_action", None) or "UNFIT",
    }
    if body.unknown_store_policy is not None:
        cfg.unknown_store_policy = _normalize_unknown_store_policy(body.unknown_store_policy)
    if body.auto_register_threshold is not None:
        cfg.auto_register_threshold = max(0.0, min(1.0, float(body.auto_register_threshold)))
    if body.enable_gemini_classifier is not None:
        cfg.enable_gemini_classifier = bool(body.enable_gemini_classifier)
    if body.min_amount_stay is not None:
        cfg.min_amount_stay = max(0, int(body.min_amount_stay))
    if body.min_amount_tour is not None:
        cfg.min_amount_tour = max(0, int(body.min_amount_tour))
    if body.orphan_object_days is not None:
        cfg.orphan_object_days = max(1, min(365, int(body.orphan_object_days)))
    if body.expired_candidate_days is not None:
        cfg.expired_candidate_days = max(1, min(365, int(body.expired_candidate_days)))
    if body.orphan_object_value is not None and body.orphan_object_unit:
        cfg.orphan_object_minutes = max(1, min(MAX_VALIDITY_MINUTES, _minutes_from_value_unit(body.orphan_object_value, body.orphan_object_unit)))
    elif body.orphan_object_minutes is not None:
        cfg.orphan_object_minutes = max(1, min(MAX_VALIDITY_MINUTES, body.orphan_object_minutes))
    if body.expired_candidate_value is not None and body.expired_candidate_unit:
        cfg.expired_candidate_minutes = max(1, min(MAX_VALIDITY_MINUTES, _minutes_from_value_unit(body.expired_candidate_value, body.expired_candidate_unit)))
    elif body.expired_candidate_minutes is not None:
        cfg.expired_candidate_minutes = max(1, min(MAX_VALIDITY_MINUTES, body.expired_candidate_minutes))
    if body.verifying_timeout_minutes is not None:
        cfg.verifying_timeout_minutes = max(0, min(MAX_VALIDITY_MINUTES, body.verifying_timeout_minutes))
    if body.verifying_timeout_action is not None:
        cfg.verifying_timeout_action = body.verifying_timeout_action if body.verifying_timeout_action in ("UNFIT", "ERROR") else "UNFIT"
    cfg.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(cfg)
    o_min_after = _cfg_orphan_minutes(cfg)
    e_min_after = _cfg_expired_minutes(cfg)
    after = {
        "unknown_store_policy": cfg.unknown_store_policy,
        "auto_register_threshold": float(cfg.auto_register_threshold or 0.90),
        "enable_gemini_classifier": bool(cfg.enable_gemini_classifier),
        "min_amount_stay": int(cfg.min_amount_stay or 60000),
        "min_amount_tour": int(cfg.min_amount_tour or 50000),
        "orphan_object_days": o_min_after // 1440,
        "expired_candidate_days": e_min_after // 1440,
        "orphan_object_minutes": o_min_after,
        "expired_candidate_minutes": e_min_after,
        "verifying_timeout_minutes": int(getattr(cfg, "verifying_timeout_minutes", None) or 0),
        "verifying_timeout_action": getattr(cfg, "verifying_timeout_action", None) or "UNFIT",
    }
    _audit_log(
        db,
        actor=actor,
        action="RULE_UPDATE",
        target_type="judgment_rule_config",
        target_id="1",
        before_json=before,
        after_json=after,
    )
    db.commit()
    return JudgmentRuleConfigResponse(
        unknown_store_policy=_normalize_unknown_store_policy(cfg.unknown_store_policy),
        auto_register_threshold=float(cfg.auto_register_threshold or 0.90),
        enable_gemini_classifier=bool(cfg.enable_gemini_classifier),
        min_amount_stay=int(cfg.min_amount_stay or 60000),
        min_amount_tour=int(cfg.min_amount_tour or 50000),
        orphan_object_days=o_min_after // 1440,
        expired_candidate_days=e_min_after // 1440,
        orphan_object_minutes=o_min_after,
        expired_candidate_minutes=e_min_after,
        verifying_timeout_minutes=int(getattr(cfg, "verifying_timeout_minutes", None) or 0),
        verifying_timeout_action=(getattr(cfg, "verifying_timeout_action", None) or "UNFIT"),
        updated_at=cfg.updated_at.isoformat() if cfg.updated_at else None,
    )


class ProcessVerifyingTimeoutResponse(BaseModel):
    processed: int = Field(0, description="처리된 건수")
    submission_ids: List[str] = Field(default_factory=list, description="처리된 receiptId 목록")
    reason: Optional[str] = Field(None, description="비활성 시 사유")


@app.post(
    "/api/v1/admin/jobs/process-verifying-timeout",
    response_model=ProcessVerifyingTimeoutResponse,
    summary="VERIFYING 대기 시간 초과 처리",
    description="판정 규칙의 verifying_timeout_minutes를 초과한 VERIFYING/PENDING_VERIFICATION 건을 UNFIT 또는 ERROR로 변경하고 FE 콜백 URL로 전송. cron/스케줄러에서 호출.",
    tags=["Admin - Jobs"],
)
async def admin_process_verifying_timeout(
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    cfg = _get_judgment_rule_config(db)
    timeout_min = int(getattr(cfg, "verifying_timeout_minutes", None) or 0)
    if timeout_min <= 0:
        return ProcessVerifyingTimeoutResponse(processed=0, submission_ids=[], reason="verifying_timeout_minutes 비활성(0)")
    processed, ids = await _process_verifying_timeout_run(db, actor=actor)
    return ProcessVerifyingTimeoutResponse(processed=processed, submission_ids=ids)


# 5-1b. 행정구역(시도/시군구) 및 통계 API (관리자)
REGIONS_DATA_PATH = os.getenv(
    "REGIONS_DATA_PATH",
    os.path.join(os.path.dirname(__file__), "PROJECT", "data", "regions_kr.json"),
)
_REGIONS_CACHE: Dict[str, Any] = {"mtime": None, "data": None}


def _load_regions_data() -> Dict[str, Any]:
    """행정구역(시도/시군구) 데이터 로드. 파일이 없으면 빈 구조 반환."""
    try:
        st = os.stat(REGIONS_DATA_PATH)
        mtime = int(st.st_mtime)
        if _REGIONS_CACHE["data"] is not None and _REGIONS_CACHE["mtime"] == mtime:
            return _REGIONS_CACHE["data"]
        with open(REGIONS_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("regions data is not a dict")
        data.setdefault("sido", [])
        data.setdefault("sigungu", {})
        _REGIONS_CACHE["mtime"] = mtime
        _REGIONS_CACHE["data"] = data
        return data
    except FileNotFoundError:
        return {"sido": [], "sigungu": {}}
    except Exception as e:
        logger.warning("Failed to load regions data: %s", e)
        return {"sido": [], "sigungu": {}}


def _build_sido_alias_map(data: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """alias/name -> {code, name}"""
    m: Dict[str, Dict[str, str]] = {}
    for it in data.get("sido", []) or []:
        code = str(it.get("code") or "").strip()
        name = str(it.get("name") or "").strip()
        if not code or not name:
            continue
        m[name] = {"code": code, "name": name}
        for a in (it.get("aliases") or []):
            a2 = str(a or "").strip()
            if a2:
                m[a2] = {"code": code, "name": name}
    return m


def _build_sigungu_name_map(data: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """sigungu name -> {code, name, sidoCode} (전체 통합, name 중복 가능성은 최초 매핑 우선)"""
    out: Dict[str, Dict[str, str]] = {}
    sigungu = data.get("sigungu") or {}
    if not isinstance(sigungu, dict):
        return out
    for sido_code, items in sigungu.items():
        for it in (items or []):
            code = str(it.get("code") or "").strip()
            name = str(it.get("name") or "").strip()
            if not code or not name:
                continue
            out.setdefault(name, {"code": code, "name": name, "sidoCode": str(sido_code)})
    return out


def _normalize_sido_from_raw(raw: Optional[str], alias_map: Dict[str, Dict[str, str]]) -> Optional[Dict[str, str]]:
    """raw(예: '강원', '강원특별자치도') -> {code,name}"""
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # address 토큰(예: '강원')을 alias로 매핑
    return alias_map.get(s)


class AdminRegionItem(BaseModel):
    code: str
    name: str


class AdminSidoListResponse(BaseModel):
    items: List[AdminRegionItem] = Field(default_factory=list)


class AdminSigunguListResponse(BaseModel):
    sidoCode: str
    sidoName: str
    items: List[AdminRegionItem] = Field(default_factory=list)


@app.get(
    "/api/v1/admin/regions/sido",
    response_model=AdminSidoListResponse,
    summary="행정구역: 시도 목록",
    description="관리자 페이지 풀다운용 시도(도) 목록을 반환. 데이터 소스: PROJECT/data/regions_kr.json",
    tags=["Admin - Regions"],
)
async def admin_list_sido(db: Session = Depends(get_db), actor: str = Depends(require_admin)):
    _ = db
    _ = actor
    data = _load_regions_data()
    items = []
    for it in data.get("sido", []) or []:
        code = str(it.get("code") or "").strip()
        name = str(it.get("name") or "").strip()
        if code and name:
            items.append(AdminRegionItem(code=code, name=name))
    return AdminSidoListResponse(items=items)


@app.get(
    "/api/v1/admin/regions/sigungu",
    response_model=AdminSigunguListResponse,
    summary="행정구역: 시군구 목록",
    description="관리자 페이지 풀다운용 시군구 목록. query의 sido는 코드(예: 42) 또는 이름(예: 강원특별자치도/강원) 모두 허용.",
    tags=["Admin - Regions"],
)
async def admin_list_sigungu(
    sido: str = Query(..., description="시도 코드 또는 이름 (예: 42 또는 강원특별자치도)"),
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    _ = db
    _ = actor
    data = _load_regions_data()
    alias_map = _build_sido_alias_map(data)
    sido_raw = (sido or "").strip()
    sido_code = None
    sido_name = None
    # code 우선
    if re.fullmatch(r"\d+", sido_raw):
        for it in data.get("sido", []) or []:
            if str(it.get("code") or "").strip() == sido_raw:
                sido_code = sido_raw
                sido_name = str(it.get("name") or "").strip()
                break
    else:
        mapped = _normalize_sido_from_raw(sido_raw, alias_map)
        if mapped:
            sido_code = mapped["code"]
            sido_name = mapped["name"]
    if not sido_code or not sido_name:
        raise HTTPException(status_code=400, detail="Invalid sido")
    items = []
    for it in (data.get("sigungu", {}) or {}).get(str(sido_code), []) or []:
        code = str(it.get("code") or "").strip()
        name = str(it.get("name") or "").strip()
        if code and name:
            items.append(AdminRegionItem(code=code, name=name))
    return AdminSigunguListResponse(sidoCode=str(sido_code), sidoName=sido_name, items=items)


# 행정지도 SVG: statgarten/maps (SGIS 통계청 API 기반) raw GitHub URL
STATGARTEN_MAPS_BASE = "https://raw.githubusercontent.com/statgarten/maps/main/svg"


def _get_statgarten_svg_url(level: str, sido_code: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    level=sido → 전국 시도 경계 SVG URL
    level=sigungu, sido_code=42 → 해당 시도 시군구 경계 SVG URL
    반환: (url, sido_name). 없으면 (None, None).
    """
    data = _load_regions_data()
    statgarten = (data or {}).get("statgarten_svg") or {}
    if level == "sido":
        filename = statgarten.get("sido") or "전국_시도_경계.svg"
        return (f"{STATGARTEN_MAPS_BASE}/{filename}", None)
    if level == "sigungu" and sido_code:
        filename = statgarten.get(str(sido_code).strip())
        if not filename:
            return (None, None)
        for it in (data.get("sido") or []):
            if str(it.get("code") or "").strip() == str(sido_code).strip():
                return (f"{STATGARTEN_MAPS_BASE}/{filename}", str(it.get("name") or "").strip())
        return (f"{STATGARTEN_MAPS_BASE}/{filename}", None)
    return (None, None)


class AdminMapSvgUrlResponse(BaseModel):
    url: str = Field(..., description="SVG 직접 로드 URL (img src 또는 object data)")
    source: str = Field(default="statgarten/maps (SGIS)", description="출처")
    level: str = Field(..., description="sido | sigungu")
    sidoCode: Optional[str] = None
    sidoName: Optional[str] = None


@app.get(
    "/api/v1/admin/maps/svg/url",
    response_model=AdminMapSvgUrlResponse,
    summary="행정지도 SVG URL 조회",
    description=(
        "관리자 페이지에서 행정지도 SVG를 표시할 때 사용할 URL을 반환. "
        "데이터 출처: [statgarten/maps](https://github.com/statgarten/maps) (통계청 SGIS API 기반).\n"
        "- level=sido: 전국 시도 경계 지도\n"
        "- level=sigungu&sido={code}: 해당 시도의 시군구 경계 지도"
    ),
    tags=["Admin - Maps"],
)
async def admin_maps_svg_url(
    level: str = Query(..., description="sido(전국 시도) | sigungu(시군구)"),
    sido: Optional[str] = Query(None, description="시도 코드(예: 42). level=sigungu 일 때 필수"),
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    _ = db
    _ = actor
    level = (level or "").strip().lower()
    if level not in ("sido", "sigungu"):
        raise HTTPException(status_code=400, detail="level must be 'sido' or 'sigungu'")
    sido_code = (sido or "").strip() or None
    if level == "sigungu" and not sido_code:
        raise HTTPException(status_code=400, detail="sido required when level=sigungu")
    data = _load_regions_data()
    if level == "sigungu" and re.fullmatch(r"\d+", str(sido_code)) is None:
        alias_map = _build_sido_alias_map(data)
        mapped = _normalize_sido_from_raw(sido_code, alias_map)
        if mapped:
            sido_code = mapped["code"]
    url, sido_name = _get_statgarten_svg_url(level, sido_code)
    if not url:
        raise HTTPException(status_code=404, detail="Map SVG not found for given level/sido")
    return AdminMapSvgUrlResponse(
        url=url,
        source="statgarten/maps (SGIS)",
        level=level,
        sidoCode=sido_code,
        sidoName=sido_name,
    )


class AdminRegionStatsItem(BaseModel):
    regionCode: Optional[str] = None
    regionName: str
    submissionCount: int = 0
    fitCount: int = 0
    totalAmount: int = 0


class AdminRegionStatsResponse(BaseModel):
    level: str = Field(..., description="SIDO | SIGUNGU | SINGLE")
    scope: Dict[str, Any] = Field(default_factory=dict, description="요청 파라미터 요약")
    items: List[AdminRegionStatsItem] = Field(default_factory=list)


@app.get(
    "/api/v1/admin/stats/by-region",
    response_model=AdminRegionStatsResponse,
    summary="행정구역별 통계",
    description=(
        "행정구역별 제출/적합/금액 집계.\n"
        "- query에 아무것도 없으면 시도별 집계\n"
        "- sido가 있으면 해당 시도의 시군구별 집계\n"
        "- sigungu가 있으면 해당 시군구 단일 집계\n"
        "집계 기준은 submission당 첫 장(seq_no=1)의 address/location을 사용."
    ),
    tags=["Admin - Stats"],
)
async def admin_stats_by_region(
    sido: Optional[str] = Query(None, description="시도 코드 또는 이름"),
    sigungu: Optional[str] = Query(None, description="시군구 코드 또는 이름"),
    dateFrom: Optional[str] = Query(None, description="기간 시작(YYYY-MM-DD). from 과 동일."),
    dateTo: Optional[str] = Query(None, description="기간 끝(YYYY-MM-DD). to 와 동일."),
    from_: Optional[str] = Query(None, alias="from", description="기간 시작(YYYY-MM-DD 등). 관리자 페이지 권장."),
    to: Optional[str] = Query(None, description="기간 끝(YYYY-MM-DD 등). 관리자 페이지 권장."),
    projectType: Optional[str] = Query(None, description="STAY | TOUR"),
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    _ = actor
    data = _load_regions_data()
    alias_map = _build_sido_alias_map(data)
    sigungu_name_map = _build_sigungu_name_map(data)

    dt_from = None
    dt_to = None
    for raw in (dateFrom, from_):
        if raw:
            try:
                dt_from = dateutil_parser.parse(raw)
                break
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid dateFrom/from")
    for raw in (dateTo, to):
        if raw:
            try:
                dt_to = dateutil_parser.parse(raw)
                break
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid dateTo/to")

    # 파라미터 정규화
    sido_code = None
    sido_name = None
    if sido:
        sraw = sido.strip()
        if re.fullmatch(r"\d+", sraw):
            mapped_name = None
            for it in data.get("sido", []) or []:
                if str(it.get("code") or "").strip() == sraw:
                    mapped_name = str(it.get("name") or "").strip()
                    break
            if not mapped_name:
                raise HTTPException(status_code=400, detail="Invalid sido")
            sido_code, sido_name = sraw, mapped_name
        else:
            mapped = _normalize_sido_from_raw(sraw, alias_map)
            if not mapped:
                raise HTTPException(status_code=400, detail="Invalid sido")
            sido_code, sido_name = mapped["code"], mapped["name"]

    sigungu_code = None
    sigungu_name = None
    if sigungu:
        graw = sigungu.strip()
        if re.fullmatch(r"\d+", graw):
            # code -> name 찾기
            found = None
            for sc, items in (data.get("sigungu", {}) or {}).items():
                for it in (items or []):
                    if str(it.get("code") or "").strip() == graw:
                        found = {"code": graw, "name": str(it.get("name") or "").strip(), "sidoCode": str(sc)}
                        break
                if found:
                    break
            if not found:
                raise HTTPException(status_code=400, detail="Invalid sigungu")
            sigungu_code, sigungu_name = found["code"], found["name"]
            if not sido_code:
                sido_code = found["sidoCode"]
                # sidoName 보강
                for it in data.get("sido", []) or []:
                    if str(it.get("code") or "").strip() == str(sido_code):
                        sido_name = str(it.get("name") or "").strip()
                        break
        else:
            # name -> code (전체 맵에서)
            found = sigungu_name_map.get(graw)
            if not found:
                raise HTTPException(status_code=400, detail="Invalid sigungu")
            sigungu_code, sigungu_name = found["code"], found["name"]
            if not sido_code:
                sido_code = found.get("sidoCode")
                for it in data.get("sido", []) or []:
                    if str(it.get("code") or "").strip() == str(sido_code):
                        sido_name = str(it.get("name") or "").strip()
                        break

    # 집계 레벨 결정
    if sigungu_code:
        level = "SINGLE"
    elif sido_code:
        level = "SIGUNGU"
    else:
        level = "SIDO"

    # submission 당 대표 지역: 첫 장(seq_no=1)의 address/location
    sido_expr = func.split_part(func.trim(ReceiptItem.address), " ", 1)
    sigungu_expr = func.coalesce(
        func.nullif(func.trim(ReceiptItem.location), ""),
        func.split_part(func.trim(ReceiptItem.address), " ", 2),
    )
    group_expr = sido_expr if level == "SIDO" else sigungu_expr

    q = (
        db.query(
            group_expr.label("region_raw"),
            func.count(Submission.submission_id).label("submission_count"),
            func.sum(case((Submission.status == "FIT", 1), else_=0)).label("fit_count"),
            func.sum(func.coalesce(Submission.total_amount, 0)).label("total_amount"),
        )
        .join(
            ReceiptItem,
            (ReceiptItem.submission_id == Submission.submission_id) & (ReceiptItem.seq_no == 1),
        )
    )
    if dt_from is not None:
        q = q.filter(Submission.created_at >= dt_from)
    if dt_to is not None:
        q = q.filter(Submission.created_at <= dt_to)
    if projectType:
        q = q.filter(Submission.project_type == projectType.strip().upper())

    if level == "SIGUNGU" and sido_name:
        # address 첫 토큰이 alias에 존재하면 sido_name과 매칭되는 코드로 정규화 후 필터 (DB 값이 '강원'처럼 짧을 수 있어 python 후처리 필요)
        # 우선 DB에서 1차 필터: address prefix로 좁힘 (과도한 오탐 방지 위해 exact name이거나 alias만)
        allowed_aliases = []
        for k, v in alias_map.items():
            if v.get("code") == str(sido_code):
                allowed_aliases.append(k)
        if allowed_aliases:
            q = q.filter(sido_expr.in_(allowed_aliases))

    if level == "SINGLE" and sigungu_name:
        q = q.filter(sigungu_expr == sigungu_name)

    rows = q.group_by(group_expr).order_by(func.count(Submission.submission_id).desc()).all()

    items: List[AdminRegionStatsItem] = []
    for r in rows:
        raw = (r[0] or "").strip()
        if not raw:
            continue
        submission_count = int(r[1] or 0)
        fit_count = int(r[2] or 0)
        total_amount = int(r[3] or 0)

        region_code = None
        region_name = raw
        if level == "SIDO":
            mapped = _normalize_sido_from_raw(raw, alias_map)
            if mapped:
                region_code = mapped["code"]
                region_name = mapped["name"]
        else:
            # SIGUNGU/SINGLE: name -> code (가능한 경우)
            found = None
            if sido_code:
                for it in (data.get("sigungu", {}) or {}).get(str(sido_code), []) or []:
                    if str(it.get("name") or "").strip() == raw:
                        found = {"code": str(it.get("code") or "").strip(), "name": raw}
                        break
            if not found:
                found = sigungu_name_map.get(raw)
            if found and found.get("code"):
                region_code = found["code"]
                region_name = found.get("name") or raw

        items.append(
            AdminRegionStatsItem(
                regionCode=region_code,
                regionName=region_name,
                submissionCount=submission_count,
                fitCount=fit_count,
                totalAmount=total_amount,
            )
        )

    scope = {
        "sido": sido_name or sido,
        "sidoCode": sido_code,
        "sigungu": sigungu_name or sigungu,
        "sigunguCode": sigungu_code,
        "from": dt_from.isoformat() if dt_from else None,
        "to": dt_to.isoformat() if dt_to else None,
        "dateFrom": dt_from.isoformat() if dt_from else None,
        "dateTo": dt_to.isoformat() if dt_to else None,
        "projectType": projectType.strip().upper() if projectType else None,
    }
    return AdminRegionStatsResponse(level=level, scope=scope, items=items)


# 5-2. 신규 상점 후보군(Unregistered Stores) 관리 API
class CandidateStoreItem(BaseModel):
    """후보 상점 한 건 (관리자 리스트용)."""
    candidate_id: str = Field(..., description="후보 ID (unregistered_stores.id)")
    store_name: Optional[str] = None
    biz_num: Optional[str] = None
    address: Optional[str] = None
    tel: Optional[str] = None
    occurrence_count: int = Field(1, description="해당 상점 영수증 접수 횟수")
    predicted_category: Optional[str] = None
    first_detected_at: Optional[str] = None  # ISO format
    recent_receipt_id: Optional[str] = Field(None, description="증거 확인용 submission_id")
    status: str = Field("PENDING_REVIEW", description="TEMP_VALID → PENDING_REVIEW 노출")


class CandidatesListResponse(BaseModel):
    total_candidates: int
    items: List[CandidateStoreItem] = Field(default_factory=list)


class ApproveCandidatesRequest(BaseModel):
    candidate_ids: List[str] = Field(..., min_length=1, description="승인할 후보 ID 목록")
    target_category: str = Field(..., description="마스터에 넣을 카테고리 (예: TOUR_SIGHTSEEING)")
    is_premium: bool = Field(False, description="프리미엄 상점 여부 (선택)")


class ApproveCandidatesResponse(BaseModel):
    approved_count: int
    failed_ids: List[str] = Field(default_factory=list, description="승인 실패한 candidate_id")


@app.get(
    "/api/v1/admin/stores/candidates",
    response_model=CandidatesListResponse,
    summary="신규 상점 후보군 목록",
    description="마스터에 없으나 OCR로 유효 판별된 상점을 빈도순/최신순으로 조회. 증거(recent_receipt_id)로 영수증 확인 가능.",
    tags=["Admin - Stores"],
)
async def list_candidate_stores(
    city_county: Optional[str] = None,
    min_occurrence: Optional[int] = None,
    sort_by: Optional[str] = "occurrence_count",
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    """관리자: 후보 상점 리스트 (시군구 필터, 최소 빈도, 정렬). TEMP_VALID + AUTO_REGISTERED(검토 필요)."""
    q = db.query(UnregisteredStore).filter(
        UnregisteredStore.status.in_(["TEMP_VALID", "AUTO_REGISTERED"])
    )
    rows = q.all()
    # 시군구 필터: 주소에서 두 번째 토큰(춘천시 등)으로 필터
    if city_county and city_county.strip():
        city = city_county.strip()
        rows = [r for r in rows if _parse_city_county_from_address(r.address) == city]
    if min_occurrence is not None and min_occurrence > 0:
        rows = [r for r in rows if (r.occurrence_count or 0) >= min_occurrence]
    # 정렬: occurrence_count 내림차순 또는 created_at 내림차순
    if sort_by == "created_at":
        rows = sorted(rows, key=lambda r: (r.created_at or datetime.min), reverse=True)
    else:
        rows = sorted(rows, key=lambda r: (r.occurrence_count or 0), reverse=True)
    items = [
        CandidateStoreItem(
            candidate_id=r.id,
            store_name=r.store_name,
            biz_num=r.biz_num,
            address=r.address,
            tel=r.tel,
            occurrence_count=r.occurrence_count or 1,
            predicted_category=r.predicted_category,
            first_detected_at=r.first_detected_at.isoformat() if r.first_detected_at else None,
            recent_receipt_id=r.recent_receipt_id or r.source_submission_id,
            status="PENDING_REVIEW",
        )
        for r in rows
    ]
    return CandidatesListResponse(total_candidates=len(items), items=items)


@app.post(
    "/api/v1/admin/stores/candidates/approve",
    response_model=ApproveCandidatesResponse,
    summary="후보 상점 마스터 편입",
    description="선택한 후보를 master_stores로 이관. 이후 해당 상점 영수증은 FIT 판정.",
    tags=["Admin - Stores"],
)
async def approve_candidate_stores(
    body: ApproveCandidatesRequest,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    """관리자: 후보 → master_stores 이관 후 status=APPROVED 처리."""
    approved = 0
    failed_ids: List[str] = []
    for cid in body.candidate_ids:
        cand = db.query(UnregisteredStore).filter(
            UnregisteredStore.id == cid,
            UnregisteredStore.status == "TEMP_VALID",
        ).first()
        if not cand:
            failed_ids.append(cid)
            continue
        try:
            before = {"status": cand.status, "store_name": cand.store_name, "biz_num": cand.biz_num, "address": cand.address}
            # master_stores에 삽입 (store_name, category_large, road_address → 트리거로 city_county 자동)
            db.execute(
                sql_text(
                    "INSERT INTO master_stores (store_name, category_large, category_small, road_address) "
                    "VALUES (:store_name, :category_large, :category_small, :road_address)"
                ),
                {
                    "store_name": cand.store_name or "",
                    "category_large": body.target_category,
                    "category_small": body.target_category,
                    "road_address": cand.address or "",
                },
            )
            cand.status = "APPROVED"
            cand.updated_at = datetime.utcnow()
            _audit_log(
                db,
                actor=actor,
                action="CANDIDATE_APPROVE",
                target_type="unregistered_store",
                target_id=cand.id,
                before_json=before,
                after_json={"status": cand.status, "target_category": body.target_category},
                meta={"receiptId": cand.recent_receipt_id or cand.source_submission_id},
            )
            approved += 1
        except Exception as e:
            logger.warning("approve candidate %s failed: %s", cid, e)
            failed_ids.append(cid)
    db.commit()
    return ApproveCandidatesResponse(approved_count=approved, failed_ids=failed_ids)


# 5-3. Submission 관리 API (관리자) — 검색/상세/override/콜백 재전송/증거 이미지
class AdminSubmissionListItem(BaseModel):
    receiptId: str
    userUuid: str
    project_type: Optional[str] = None
    status: Optional[str] = None
    total_amount: int = 0
    created_at: Optional[str] = None


class AdminSubmissionListResponse(BaseModel):
    total: int
    items: List[AdminSubmissionListItem] = Field(default_factory=list)


@app.get(
    "/api/v1/admin/submissions",
    response_model=AdminSubmissionListResponse,
    summary="신청 목록 검색(관리자)",
    tags=["Admin - Submissions"],
)
async def admin_list_submissions(
    status: Optional[str] = None,
    userUuid: Optional[str] = None,
    receiptId: Optional[str] = None,
    dateFrom: Optional[str] = None,
    dateTo: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    q = db.query(Submission)
    if receiptId:
        q = q.filter(Submission.submission_id == receiptId.strip())
    if userUuid:
        q = q.filter(Submission.user_uuid == userUuid.strip())
    if status:
        q = q.filter(Submission.status == status.strip())
    if dateFrom:
        try:
            dt = dateutil_parser.parse(dateFrom)
            q = q.filter(Submission.created_at >= dt)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid dateFrom")
    if dateTo:
        try:
            dt = dateutil_parser.parse(dateTo)
            q = q.filter(Submission.created_at <= dt)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid dateTo")

    total = q.count()
    rows = (
        q.order_by(Submission.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = [
        AdminSubmissionListItem(
            receiptId=r.submission_id,
            userUuid=r.user_uuid,
            project_type=r.project_type,
            status=r.status,
            total_amount=r.total_amount or 0,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]
    return AdminSubmissionListResponse(total=total, items=items)


class AdminSubmissionDetailResponse(BaseModel):
    receiptId: str
    submission: Dict[str, Any]
    statusPayload: Dict[str, Any]


def _build_status_payload_admin(submission: Submission, item_rows: List[ReceiptItem]) -> Dict[str, Any]:
    """관리자용 상세: ocr_raw 포함."""
    base = _build_status_payload(submission, item_rows)
    # 콜백 최적화 함수(_build_status_payload)는 ocr_raw를 제외하므로, 관리자용은 다시 붙인다.
    # item_id로 매칭해 주입
    raw_by_id = {str(it.item_id): it.ocr_raw for it in item_rows}
    for it in base.get("items", []):
        iid = it.get("item_id")
        it["ocr_raw"] = raw_by_id.get(iid)
    return base


@app.get(
    "/api/v1/admin/submissions/{receiptId}",
    response_model=AdminSubmissionDetailResponse,
    summary="신청 단건 상세(관리자)",
    tags=["Admin - Submissions"],
)
async def admin_get_submission(receiptId: str, db: Session = Depends(get_db), actor: str = Depends(require_admin)):
    rid = _sanitize_receipt_id(receiptId)
    submission = db.query(Submission).filter(Submission.submission_id == rid).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    item_rows = (
        db.query(ReceiptItem)
        .filter(ReceiptItem.submission_id == rid)
        .order_by(ReceiptItem.seq_no.asc())
        .all()
    )
    status_payload = _build_status_payload_admin(submission, item_rows)
    return AdminSubmissionDetailResponse(
        receiptId=rid,
        submission={
            "submission_id": submission.submission_id,
            "user_uuid": submission.user_uuid,
            "project_type": submission.project_type,
            "campaign_id": submission.campaign_id,
            "status": submission.status,
            "total_amount": submission.total_amount or 0,
            "global_fail_reason": submission.global_fail_reason,
            "fail_reason": submission.fail_reason,
            "audit_trail": submission.audit_trail,
            "created_at": submission.created_at.isoformat() if submission.created_at else None,
            "user_input_snapshot": getattr(submission, "user_input_snapshot", None),
        },
        statusPayload=status_payload,
    )


class AdminReceiptImageItem(BaseModel):
    item_id: str
    doc_type: Optional[str] = None
    image_key: str
    image_url: str


class AdminReceiptImagesResponse(BaseModel):
    receiptId: str
    expiresIn: int = 600
    items: List[AdminReceiptImageItem] = Field(default_factory=list)


@app.get(
    "/api/v1/admin/receipts/{receiptId}/images",
    response_model=AdminReceiptImagesResponse,
    summary="신청 이미지 presigned GET(관리자)",
    tags=["Admin - Submissions"],
)
async def admin_get_receipt_images(receiptId: str, db: Session = Depends(get_db), actor: str = Depends(require_admin)):
    rid = _sanitize_receipt_id(receiptId)
    item_rows = (
        db.query(ReceiptItem)
        .filter(ReceiptItem.submission_id == rid)
        .order_by(ReceiptItem.seq_no.asc())
        .all()
    )
    items: List[AdminReceiptImageItem] = []
    for it in item_rows:
        key = (it.image_key or "").strip()
        if not key:
            continue
        params = {"Bucket": S3_BUCKET, "Key": key}
        # 저장 시 Content-Type이 잘못돼 있어도 브라우저가 이미지로 렌더하도록 응답 타입 지정
        if key.lower().endswith(".png"):
            params["ResponseContentType"] = "image/png"
        elif key.lower().endswith((".jpg", ".jpeg")):
            params["ResponseContentType"] = "image/jpeg"
        url = s3_client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=600,
        )
        items.append(
            AdminReceiptImageItem(
                item_id=str(it.item_id),
                doc_type=it.doc_type,
                image_key=key,
                image_url=url,
            )
        )
    return AdminReceiptImagesResponse(receiptId=rid, items=items)


class AdminOverrideRequest(BaseModel):
    status: str
    reason: str
    override_reward_amount: Optional[int] = None
    resend_callback: bool = False


class AdminOverrideResponse(BaseModel):
    receiptId: str
    previous_status: str
    new_status: str
    updated_at: str


@app.post(
    "/api/v1/admin/submissions/{receiptId}/override",
    response_model=AdminOverrideResponse,
    summary="수동 판정 변경(override)",
    tags=["Admin - Submissions"],
)
async def admin_override_submission(
    receiptId: str,
    body: AdminOverrideRequest,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    rid = _sanitize_receipt_id(receiptId)
    submission = db.query(Submission).filter(Submission.submission_id == rid).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    before = {"status": submission.status, "fail_reason": submission.fail_reason, "total_amount": submission.total_amount or 0}
    prev_status = submission.status or ""
    submission.status = body.status.strip()
    submission.updated_at = datetime.utcnow()
    submission.fail_reason = None if submission.status == "FIT" else (body.reason.strip() or submission.fail_reason)
    submission.global_fail_reason = submission.fail_reason
    # 감사/추적을 위해 audit_trail에 override 기록을 append
    override_line = f"OVERRIDE({datetime.utcnow().isoformat()}): {body.reason.strip()}"
    existing = submission.audit_trail or submission.audit_log or ""
    submission.audit_trail = (existing + " | " + override_line).strip(" |") if existing else override_line
    submission.audit_log = submission.audit_trail
    if body.override_reward_amount is not None:
        # rewardAmount는 응답 계산 로직이 있으므로, 필요 시 별도 컬럼 도입이 더 안전함.
        pass
    db.commit()
    db.refresh(submission)
    _audit_log(
        db,
        actor=actor,
        action="SUBMISSION_OVERRIDE",
        target_type="submission",
        target_id=rid,
        before_json=before,
        after_json={"status": submission.status, "fail_reason": submission.fail_reason, "audit_trail": submission.audit_trail},
        meta={"resend_callback": bool(body.resend_callback)},
    )
    db.commit()
    if body.resend_callback:
        item_rows = (
            db.query(ReceiptItem)
            .filter(ReceiptItem.submission_id == rid)
            .order_by(ReceiptItem.seq_no.asc())
            .all()
        )
        payload = _build_status_payload(submission, item_rows)
        await _send_result_callback(rid, payload, purpose="resend", actor=actor)
        _audit_log(
            db,
            actor=actor,
            action="CALLBACK_RESEND",
            target_type="submission",
            target_id=rid,
            meta={"trigger": "override"},
        )
        db.commit()
    return AdminOverrideResponse(
        receiptId=rid,
        previous_status=prev_status,
        new_status=submission.status,
        updated_at=datetime.utcnow().isoformat(),
    )


class AdminCallbackResendRequest(BaseModel):
    target_url: Optional[str] = None


class AdminCallbackResendResponse(BaseModel):
    receiptId: str
    sent: bool


@app.post(
    "/api/v1/admin/submissions/{receiptId}/callback/resend",
    response_model=AdminCallbackResendResponse,
    responses={404: {"description": "Submission not found"}},
    summary="콜백 재전송(관리자)",
    description="OCR 결과를 지정 URL(또는 환경변수 OCR_RESULT_CALLBACK_URL)로 재전송. 관리자 검수 완료 후 FE에 결과를 다시 보낼 때 사용.",
    tags=["Admin - Callback"],
)
async def admin_resend_callback(
    receiptId: str,
    body: AdminCallbackResendRequest,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    rid = _sanitize_receipt_id(receiptId)
    submission = db.query(Submission).filter(Submission.submission_id == rid).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    item_rows = (
        db.query(ReceiptItem)
        .filter(ReceiptItem.submission_id == rid)
        .order_by(ReceiptItem.seq_no.asc())
        .all()
    )
    payload = _build_status_payload(submission, item_rows)
    await _send_result_callback(rid, payload, target_url=body.target_url, purpose="resend", actor=actor)
    _audit_log(
        db,
        actor=actor,
        action="CALLBACK_RESEND",
        target_type="submission",
        target_id=rid,
        meta={"target_url": body.target_url},
    )
    db.commit()
    return AdminCallbackResendResponse(receiptId=rid, sent=True)


@app.post(
    "/api/v1/admin/submissions/{receiptId}/callback/verify",
    responses={404: {"description": "Submission not found"}},
    summary="콜백 검증(즉시 송출)",
    description="현재 DB 기준 상태를 콜백 URL로 즉시 전송하고, 전송 결과(성공/실패/스킵)를 응답으로 반환. 콜백 URL 설정 여부 확인 및 수동 재전송 테스트용.",
    tags=["Admin - Callback"],
)
async def admin_verify_callback(
    receiptId: str,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    rid = _sanitize_receipt_id(receiptId)
    submission = db.query(Submission).filter(Submission.submission_id == rid).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    item_rows = (
        db.query(ReceiptItem)
        .filter(ReceiptItem.submission_id == rid)
        .order_by(ReceiptItem.seq_no.asc())
        .all()
    )
    payload = _build_status_payload(submission, item_rows)
    result = await _send_result_callback(rid, payload, purpose="verify", actor=actor)
    _audit_log(
        db,
        actor=actor,
        action="CALLBACK_VERIFY",
        target_type="submission",
        target_id=rid,
        meta={"result": result},
    )
    db.commit()
    return result


@app.get(
    "/api/v1/admin/submissions/{receiptId}/callback/logs",
    responses={404: {"description": "Submission not found"}},
    summary="콜백 전송 로그 조회",
    description="해당 receiptId에 대한 콜백 전송/재전송/검증 시도 이력을 조회. CALLBACK_SEND, CALLBACK_RESEND, CALLBACK_VERIFY 액션만 포함.",
    tags=["Admin - Callback"],
)
async def admin_get_callback_logs(
    receiptId: str,
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    rid = _sanitize_receipt_id(receiptId)
    rows = (
        db.query(AdminAuditLog)
        .filter(
            AdminAuditLog.target_type == "submission",
            AdminAuditLog.target_id == rid,
            AdminAuditLog.action.in_(["CALLBACK_SEND", "CALLBACK_RESEND", "CALLBACK_VERIFY"]),
        )
        .order_by(AdminAuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    _ = actor  # 권한 체크용
    return {
        "receiptId": rid,
        "items": [
            {
                "id": int(r.id),
                "action": r.action,
                "actor": r.actor,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "meta": r.meta,
            }
            for r in rows
        ],
    }


# 6. Naver 영수증 OCR 연동 (CLOVA Document OCR > 영수증)
# - 공식 권장: 장축 1960px 이하, JPEG 품질은 인식률 위해 90 권장 (PROJECT/네이버_CLOVA_OCR_레퍼런스_및_인식률_검토.md)
MAX_OCR_DIMENSION = int(os.getenv("OCR_MAX_DIMENSION", "1960"))
OCR_JPEG_QUALITY = int(os.getenv("OCR_JPEG_QUALITY", "90"))
# 인식률 향상: 저해상도 업스케일(1=활성), 업스케일 적용 한계(이 값 미만이면 장축 1960까지 확대), 작은 이미지 PNG 전송(1=활성)
OCR_UPSCALE_SMALL = os.getenv("OCR_UPSCALE_SMALL", "0").strip().lower() in ("1", "true", "yes")
OCR_UPSCALE_MAX_SIDE = int(os.getenv("OCR_UPSCALE_MAX_SIDE", "1200"))
OCR_SEND_PNG_WHEN_SMALL = os.getenv("OCR_SEND_PNG_WHEN_SMALL", "0").strip().lower() in ("1", "true", "yes")


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
    리사이징(장축 최대 MAX_OCR_DIMENSION) + 압축. 인식률 향상 옵션:
    - 저해상도 업스케일(OCR_UPSCALE_SMALL=1): 장축이 OCR_UPSCALE_MAX_SIDE 미만이면 1960까지 확대.
    - 작은 이미지 PNG 전송(OCR_SEND_PNG_WHEN_SMALL=1): 최종 장축이 작으면 JPEG 대신 PNG로 전송(경계 보존).
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img = ImageOps.autocontrast(img, cutoff=1)
        img = ImageEnhance.Sharpness(img).enhance(1.2)
        w, h = img.size
        long_side = max(w, h)
        if w > MAX_OCR_DIMENSION or h > MAX_OCR_DIMENSION:
            ratio = min(MAX_OCR_DIMENSION / w, MAX_OCR_DIMENSION / h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)
        elif OCR_UPSCALE_SMALL and long_side < OCR_UPSCALE_MAX_SIDE and long_side > 0:
            ratio = MAX_OCR_DIMENSION / long_side
            nw, nh = int(w * ratio), int(h * ratio)
            if nw > 0 and nh > 0:
                img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        w, h = img.size
        long_side = max(w, h)
        use_png = OCR_SEND_PNG_WHEN_SMALL and long_side <= OCR_UPSCALE_MAX_SIDE
        buf = io.BytesIO()
        if use_png:
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), "image/png"
        img.save(buf, format="JPEG", quality=OCR_JPEG_QUALITY, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return image_bytes, content_type


def _image_format_from_content_type(content_type: str) -> str:
    """Content-Type → 네이버 OCR format (jpg|png)."""
    if "png" in content_type:
        return "png"
    return "jpg"


def _strip_trailing_date_junk(s: str) -> str:
    """
    날짜 문자열 끝의 괄호·요일 등 비날짜 접미사 제거.
    예: "26.02.22 (일)" → "26.02.22", "26-02-22-(일)" → "26-02-22"
    """
    if not s:
        return s
    s = re.sub(r"[(\（].*$", "", s.strip())
    return s.strip(" -")


def _normalize_and_validate_2026_date(date_text: str) -> Tuple[bool, Optional[str]]:
    """
    OCR 날짜 정규화 후 2026년 유효성 검사.
    Step1: 괄호·요일 등 비날짜 접미사 제거 (예: "26.02.22 (일)" → "26.02.22")
    Step2: 구분자(., /, 공백)를 '-'로 치환
    Step3: 2026 또는 26으로 시작하는지 확인
    Step4: dateutil.parser로 파싱 후 유효한 날짜인지 검증
    반환: (2026년 유효 여부, 정규화된 날짜 문자열 또는 None)
    """
    if not date_text or not isinstance(date_text, str):
        return False, None
    s = date_text.strip()
    s = _strip_trailing_date_junk(s)
    s = re.sub(r"[/.\s]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("- ")
    if not re.match(r"^(2026|26)", s):
        return False, None
    if s.startswith("26") and (len(s) == 2 or s[2] in "-./"):
        s = "20" + s
    try:
        parsed = dateutil_parser.parse(s)
        if parsed.year != 2026:
            return False, None
        normalized = parsed.strftime("%Y/%m/%d")
        return True, normalized
    except (ValueError, TypeError):
        return False, None


def _normalize_pay_date_canonical(raw: Optional[str]) -> Optional[str]:
    """
    결제일자를 YYYY/MM/DD 형식으로 통일. (26/01/10 → 2026/01/10, 26.02.22 (일) → 2026/02/22)
    파싱 실패 시 원문 반환(또는 None). receipt_item 저장·API 응답에 사용.
    """
    if not raw or not isinstance(raw, str):
        return raw
    s = raw.strip()
    if not s:
        return None
    s = _strip_trailing_date_junk(s)
    s = re.sub(r"[/.\s]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("- ")
    # 26-01-10 → 2026-01-10
    if len(s) >= 2 and s[:2] == "26" and (len(s) == 2 or s[2] in "-."):
        s = "20" + s
    try:
        parsed = dateutil_parser.parse(s)
        return parsed.strftime("%Y/%m/%d")
    except (ValueError, TypeError):
        return raw if raw.strip() else None


def _validate_naver_ocr_response(ocr_data: Any, receipt_id: str) -> None:
    """
    네이버 OCR 응답 검증. 형식 오류 시 ValueError 발생 → 호출부에서 ERROR_OCR 처리.
    - 200 OK이지만 body에 error 또는 images 누락/비정상 시 분석 불가로 간주.
    - 영수증 API는 images[].receipt.result 구조; inferResult는 있는 경우만 검사.
    """
    if not isinstance(ocr_data, dict):
        raise ValueError(f"Naver OCR response is not a dict: type={type(ocr_data).__name__}")
    if ocr_data.get("error"):
        err = ocr_data["error"]
        msg = err.get("message", err) if isinstance(err, dict) else str(err)
        raise ValueError(f"Naver OCR error in response: {msg}")
    images = ocr_data.get("images")
    if not isinstance(images, list) or len(images) == 0:
        raise ValueError("Naver OCR response has no images or empty images array")
    first = images[0] if isinstance(images[0], dict) else {}
    infer_result = first.get("inferResult") or first.get("message")
    if infer_result is not None and isinstance(infer_result, str):
        if infer_result.upper() not in ("SUCCESS", "SUCCESS_OK"):
            raise ValueError(f"Naver OCR inferResult not success: {infer_result}")


async def _call_naver_ocr_binary(
    image_binary: bytes, receipt_id: str, image_format: str = "jpg"
) -> dict:
    """
    CLOVA OCR 영수증 API — multipart/form-data(바이너리) 전송.
    Base64 대비 용량·메모리 효율적이며 네이버 권장 방식.
    응답 검증 후 반환; 형식 오류 시 ValueError로 호출부에서 ERROR_OCR 처리.
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
        try:
            ocr_data = response.json()
        except Exception as e:
            logger.warning("Naver OCR response is not JSON: %s", e)
            raise ValueError(f"Naver OCR response is not valid JSON: {e}") from e
        _validate_naver_ocr_response(ocr_data, receipt_id)
        return ocr_data


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
        pay_date = _normalize_pay_date_canonical(pay_date) or pay_date
        # 상호명
        store_info = result.get("storeInfo") or {}
        store_name = (store_info.get("name") or {}).get("text") or ""
        store_name = re.sub(r"\s+", " ", store_name).strip()
        # 주소: address 단일 객체 또는 addresses 배열 (CLOVA 형식)
        addr_obj = store_info.get("address") or {}
        address = (addr_obj.get("text") or "").strip()
        if not address:
            addrs = store_info.get("addresses") or []
            if isinstance(addrs, list) and len(addrs) > 0:
                first_addr = addrs[0] if isinstance(addrs[0], dict) else {}
                address = (first_addr.get("text") or "").strip()
        address = _normalize_address(address) or address
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
        return _normalize_biz_num(biz) or None
    except (KeyError, TypeError, ValueError):
        return None


# 카드번호 구분: 현금=0000, 카드번호 없음/마스킹(****)=1000, 유효한 번호=마지막 4자리
CARD_NUM_CASH = "0000"
CARD_NUM_NO_CARD = "1000"


def _normalize_card_num(raw: Optional[str]) -> str:
    """
    카드번호 정규화:
    - 숫자 4자리 이상이면 마지막 4자리 저장
    - 비어 있거나 **** 등 마스킹/미표시면 '1000'(카드번호 없음)
    - 현금 여부는 _extract_card_num에서 OCR 전체로 판별 → '0000'
    """
    text = (raw or "").strip()
    if not text or re.match(r"^[\s*\-]+$", text):
        return CARD_NUM_NO_CARD
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) >= 4:
        return digits[-4:]
    return CARD_NUM_NO_CARD


def _digits_only(raw: Optional[str]) -> str:
    return re.sub(r"[^0-9]", "", (raw or "").strip())


def _normalize_biz_num(raw: Optional[str]) -> Optional[str]:
    """
    사업자등록번호 정규화:
    - 숫자만 추출 후 길이 10이면 000-00-00000 포맷으로 통일
    - 그 외는 원문/None
    """
    s = (raw or "").strip()
    if not s:
        return None
    d = _digits_only(s)
    if len(d) == 10:
        return f"{d[:3]}-{d[3:5]}-{d[5:]}"
    return s


def _normalize_tel(raw: Optional[str]) -> Optional[str]:
    """
    전화번호 정규화:
    - 숫자만 추출 후 02/지역번호/휴대폰 기준으로 하이픈 포맷
    - 국제코드 82로 시작하면 0으로 치환
    """
    s = (raw or "").strip()
    if not s:
        return None
    d = _digits_only(s)
    if d.startswith("82") and len(d) >= 10:
        d = "0" + d[2:]
    if len(d) == 8:
        return f"{d[:4]}-{d[4:]}"
    if d.startswith("02"):
        if len(d) == 9:
            return f"02-{d[2:5]}-{d[5:]}"
        if len(d) == 10:
            return f"02-{d[2:6]}-{d[6:]}"
    if len(d) == 10:
        return f"{d[:3]}-{d[3:6]}-{d[6:]}"
    if len(d) == 11:
        return f"{d[:3]}-{d[3:7]}-{d[7:]}"
    return s


def _normalize_text_line(raw: Optional[str]) -> Optional[str]:
    """한 줄 텍스트 정규화: trim, 연속 공백 1칸. receipt_items store_name/location 등 자산화용."""
    if raw is None:
        return None
    s = (raw if isinstance(raw, str) else str(raw)).strip()
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _normalize_store_name(raw: Optional[str]) -> Optional[str]:
    """상호명 정규화: _normalize_text_line과 동일."""
    return _normalize_text_line(raw)


def _normalize_location(raw: Optional[str]) -> Optional[str]:
    """위치/시군 정규화: _normalize_text_line과 동일."""
    return _normalize_text_line(raw)


def _normalize_amount(raw: Optional[Any]) -> Optional[int]:
    """금액 정규화: 정수만 저장. str이면 쉼표 제거 후 파싱, 음수/비정상 → None."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    s = (raw if isinstance(raw, str) else str(raw)).strip().replace(",", "")
    digits = re.sub(r"[^0-9]", "", s)
    if not digits:
        return None
    try:
        n = int(digits)
        return n if n >= 0 else None
    except (ValueError, TypeError):
        return None


def _normalize_pay_date_for_storage(raw: Optional[str]) -> Optional[str]:
    """결제일자 저장용: YYYY-MM-DD(ISO)로 통일. receipt_items.pay_date 자산화용."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    s = re.sub(r"[/.\s]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("- ")
    if len(s) >= 2 and s[:2] == "26" and (len(s) == 2 or s[2] in "-."):
        s = "20" + s
    try:
        parsed = dateutil_parser.parse(s)
        return parsed.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        c = _normalize_pay_date_canonical(raw)
        if c:
            return c.replace("/", "-")  # YYYY/MM/DD → YYYY-MM-DD
        return None


def _normalize_address(raw: Optional[str]) -> Optional[str]:
    """
    주소 정규화(외부 표시/자산화용):
    - 양쪽 공백 제거
    - 중복 공백 1칸으로 축소
    - '강원도 ...' 표기를 '강원특별자치도 ...'로 통일 (선두 토큰 기준)
    """
    s = (raw or "").strip()
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^강원도(\s+)", r"강원특별자치도\1", s)
    return s


def _is_cash_payment(ocr_data: dict) -> bool:
    """OCR 결과에서 결제 수단이 현금인지 여부."""
    try:
        blob = json.dumps(ocr_data, ensure_ascii=False)
        return "현금" in blob
    except Exception:
        return False


def _extract_card_num(ocr_data: dict) -> str:
    """
    OCR 결과에서 카드번호(last4) 추출.
    - 결제 수단이 '현금'이면 '0000'
    - 카드번호 없음/**** 마스킹/미표시면 '1000'
    - 유효한 숫자 4자리 이상이면 마지막 4자리
    """
    try:
        images = ocr_data.get("images") or []
        if not images:
            return CARD_NUM_NO_CARD
        result = (images[0].get("receipt") or {}).get("result") or {}
        if _is_cash_payment(ocr_data):
            return CARD_NUM_CASH
        card_info = (result.get("paymentInfo") or {}).get("cardInfo") or {}
        card_num_obj = card_info.get("number") or {}
        raw_text = card_num_obj.get("text")
        return _normalize_card_num(raw_text)
    except Exception:
        return CARD_NUM_NO_CARD


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
OCR_CONFIDENCE_THRESHOLD = int(os.getenv("OCR_CONFIDENCE_THRESHOLD", "90"))  # >= 이 값이면 OCR 우선 신뢰(사용자 입력 대체 안 함)
# 저신뢰도 또는 핵심 필드(상점명·사업자번호·주소) 누락 시 수동 검수(보정) 유도
OCR_LOW_CONFIDENCE_REVIEW_THRESHOLD = int(os.getenv("OCR_LOW_CONFIDENCE_REVIEW_THRESHOLD", "70"))
OCR_KEY_FIELDS_MIN_FILLED = int(os.getenv("OCR_KEY_FIELDS_MIN_FILLED", "2"))  # 3개 중 최소 채워져야 하는 개수
AMOUNT_MISMATCH_RATIO_THRESHOLD = 0.10  # 10% 이상 차이 시 수동 검증 보류


def _should_require_manual_review_for_low_quality(
    store_name: Optional[str],
    biz_num: Optional[str],
    address: Optional[str],
    confidence: Optional[int],
) -> bool:
    """
    상점명·사업자번호·주소 중 충분히 채워지지 않았고, 컨피던스가 낮으면 수동 검수(보정) 대상.
    반환 True 시 PENDING_VERIFICATION(OCR_004) 처리하여 관리자가 보정할 수 있게 함.
    """
    filled = sum(1 for v in (store_name, biz_num, address) if v and str(v).strip())
    if filled >= OCR_KEY_FIELDS_MIN_FILLED:
        return False
    if confidence is not None and confidence >= OCR_LOW_CONFIDENCE_REVIEW_THRESHOLD:
        return False
    return True


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
            return _normalize_tel(tel_text) or None
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


def _get_user_input_for_document(
    data: Optional[Union[StayData, TourData, DataWithItems]], doc_index: int
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """장 인덱스에 대한 사용자 입력 (amount, pay_date, location). 없으면 (None, None, None)."""
    if data is None:
        return None, None, None
    if isinstance(data, DataWithItems):
        if doc_index < 0 or doc_index >= len(data.items):
            return None, None, None
        it = data.items[doc_index]
        return it.amount, it.payDate or None, it.location
    if isinstance(data, StayData) and doc_index == 0:
        return data.amount, data.payDate or None, data.location
    if isinstance(data, TourData):
        return data.amount, data.payDate or None, None
    return None, None, None


def _get_user_total_amount(
    data: Optional[Union[StayData, TourData, DataWithItems]], doc_count: int
) -> Optional[int]:
    """TOUR 시 사용자 입력 합산 금액 (DataWithItems면 items 합산, 아니면 단일 amount)."""
    if data is None:
        return None
    if isinstance(data, DataWithItems):
        return sum(data.items[i].amount for i in range(min(len(data.items), doc_count)))
    if isinstance(data, TourData):
        return data.amount
    return None


def _auto_register_store(
    db: Session,
    submission_id: str,
    store_name: str,
    address: Optional[str],
    biz_num: Optional[str],
    tel: Optional[str],
    predicted_category: str,
    category_confidence: float,
    classifier_type: str,
) -> None:
    """고신뢰도 자동 분류 시 master_stores + unregistered_stores(AUTO_REGISTERED) 삽입. 이후 동일 상점은 FIT."""
    try:
        db.execute(
            sql_text(
                "INSERT INTO master_stores (store_name, category_large, category_small, road_address) "
                "VALUES (:store_name, :category_large, :category_small, :road_address)"
            ),
            {
                "store_name": store_name or "",
                "category_large": predicted_category,
                "category_small": predicted_category,
                "road_address": address or "",
            },
        )
    except Exception as e:
        logger.warning("auto_register_store master_stores insert failed: %s", e)
        return
    now = datetime.utcnow()
    db.add(
        UnregisteredStore(
            store_name=store_name,
            biz_num=biz_num,
            address=address,
            tel=tel,
            status="AUTO_REGISTERED",
            source_submission_id=submission_id,
            occurrence_count=1,
            first_detected_at=now,
            recent_receipt_id=submission_id,
            predicted_category=predicted_category,
            category_confidence=category_confidence,
            classifier_type=classifier_type,
            updated_at=now,
        )
    )


def _register_new_candidate_store(
    db: Session,
    submission_id: str,
    parsed: Dict[str, Any],
    ocr_raw: Optional[Dict[str, Any]],
    predicted_category: Optional[str] = None,
    category_confidence: Optional[float] = None,
    classifier_type: Optional[str] = None,
) -> None:
    """
    마스터 미등록 상점을 임시 등록(TEMP_VALID).
    biz_num+address+tel 조합 우선으로 중복 등록 방지.
    predicted_category/confidence/classifier_type 은 업종 자동 분류 결과(선택).
    """
    biz_num = _normalize_biz_num((parsed.get("businessNum") or "").strip()) if parsed.get("businessNum") else None
    address = _normalize_address((parsed.get("address") or "").strip()) if parsed.get("address") else None
    tel = _extract_store_tel(ocr_raw or {}) if ocr_raw else None
    store_name_raw = (parsed.get("storeName") or "").strip() or None
    store_name = re.sub(r"\s+", " ", store_name_raw).strip() if store_name_raw else None

    q = db.query(UnregisteredStore).filter(UnregisteredStore.status == "TEMP_VALID")
    if biz_num:
        q = q.filter(UnregisteredStore.biz_num == biz_num)
    if address:
        q = q.filter(UnregisteredStore.address == address)
    if tel:
        q = q.filter(UnregisteredStore.tel == tel)
    exists = q.first()
    now = datetime.utcnow()
    if exists:
        exists.occurrence_count = (exists.occurrence_count or 0) + 1
        exists.recent_receipt_id = submission_id
        exists.updated_at = now
        if predicted_category is not None:
            exists.predicted_category = predicted_category
        if category_confidence is not None:
            exists.category_confidence = category_confidence
        if classifier_type is not None:
            exists.classifier_type = classifier_type
        return

    db.add(
        UnregisteredStore(
            store_name=store_name,
            biz_num=biz_num,
            address=address,
            tel=tel,
            status="TEMP_VALID",
            source_submission_id=submission_id,
            occurrence_count=1,
            first_detected_at=now,
            recent_receipt_id=submission_id,
            predicted_category=predicted_category,
            category_confidence=category_confidence,
            classifier_type=classifier_type,
            updated_at=now,
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
        "OCR_004": "OCR_004 (인식 불량·수동 검수 보정)",
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
        str(code).strip(),
    )
    return m.group(1) if m else None


def _resolve_item_status_error(code: Optional[str]) -> Tuple[str, Optional[str], Optional[str]]:
    """
    코드 하나로 status / error_code / error_message 를 일관되게 결정.
    반환: (status, normalized_error_code, error_message)
    """
    normalized = _normalize_error_code(code) or code
    if not normalized:
        return "FIT", None, None
    status = _status_for_code(normalized)
    msg = _fail_message(normalized)
    return status, normalized, msg


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
    if c in ("PENDING_VERIFICATION", "OCR_004"):
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
        raw_status = asset.get("status", "PENDING")
        raw_code = asset.get("error_code")
        code = _normalize_error_code(raw_code) or raw_code
        if raw_status == "ERROR_OCR" and not code:
            code = "OCR_001"
        if code is None:
            status = raw_status or "PENDING"
            normalized_code = None
            error_msg = None
        else:
            status, normalized_code, error_msg = _resolve_item_status_error(code)
        amount = _normalize_amount(p.get("amount"))
        card_num = _normalize_card_num(p.get("cardNum"))
        raw_pay = (p.get("payDate") or "").strip() or None
        pay_date_stored = _normalize_pay_date_for_storage(raw_pay) if raw_pay else None
        store_name = _normalize_store_name(p.get("storeName"))
        biz_num = _normalize_biz_num((p.get("businessNum") or "").strip()) if p.get("businessNum") else None
        address = _normalize_address((p.get("address") or "").strip()) if (p.get("address") or "").strip() else None
        location = _normalize_location(p.get("location"))
        item = ReceiptItem(
            submission_id=submission_id,
            seq_no=idx,
            doc_type=asset.get("docType", (documents[idx - 1].get("docType") if idx - 1 < len(documents) else "RECEIPT")),
            image_key=(asset.get("imageKey") or "").strip() or "",
            store_name=store_name,
            biz_num=biz_num,
            pay_date=pay_date_stored or raw_pay,
            amount=amount,
            address=address,
            location=location,
            card_num=card_num,
            status=status,
            error_code=normalized_code,
            error_message=error_msg,
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
    - FIT item 금액 합산 기준으로 최종 판정.
    - 1개 이상 영수증이 조건 충족(합산 >= 기준)이면 개별 장의 UNFIT(업종/지역/날짜)로 전체를 덮지 않고 FIT 처리.
    """
    submission.total_amount = total_amount
    submission.updated_at = datetime.utcnow()
    resolved = _normalize_error_code(fail_code) or fail_code
    # 1개 이상 조건 충족 시: 개별 장만의 사유(UNFIT_CATEGORY/REGION/DATE)는 전체를 UNFIT로 두지 않음
    if total_amount >= min_criteria and resolved in ("UNFIT_CATEGORY", "UNFIT_REGION", "UNFIT_DATE"):
        resolved = None
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
        parsed["cardNum"] = CARD_NUM_NO_CARD
        parsed["confidenceScore"] = _extract_confidence_score(ocr_data)

    return {
        "imageKey": image_key,
        "docType": doc_type,
        "parsed": parsed,
        "ocrRaw": ocr_data,
    }


async def analyze_receipt_task(req: CompleteRequest):
    """
    1:N 구조 기준 OCR 분석: submission(parent) + receipt_items(children) 자산화.
    receiptId당 1개만 실행되도록 Complete 단계에서 원자적 PENDING→PROCESSING 전환 사용.
    태스크마다 별도 DB 세션(SessionLocal()) 사용 → 서로 다른 receiptId 간 병렬 처리 시 충돌 없음.
    """
    db = SessionLocal()
    submission = db.query(Submission).filter(Submission.submission_id == req.receiptId).first()
    if not submission:
        db.close()
        return

    try:
        rule_cfg = _get_judgment_rule_config(db)
        unknown_store_policy = _normalize_unknown_store_policy(rule_cfg.unknown_store_policy)
        auto_register_threshold = float(rule_cfg.auto_register_threshold or CLASSIFIER_AUTO_THRESHOLD)
        auto_register_threshold = max(0.0, min(1.0, auto_register_threshold))
        use_gemini_classifier = bool(rule_cfg.enable_gemini_classifier)
        min_amount_stay = int(rule_cfg.min_amount_stay or 60000)
        min_amount_tour = int(rule_cfg.min_amount_tour or 50000)

        documents = _build_documents_from_request(req)
        if not documents:
            submission.status = "UNFIT"
            submission.updated_at = datetime.utcnow()
            submission.total_amount = 0
            submission.fail_reason = _global_fail_reason("BIZ_010")
            submission.global_fail_reason = submission.fail_reason
            submission.audit_log = "문서 구성 요건 불충족"
            submission.audit_trail = submission.audit_log
            db.commit()
            return

        submission.project_type = req.type
        # VERIFYING 전에 placeholder를 먼저 넣고 한 번에 commit → GET이 VERIFYING을 볼 때 항상 items 존재
        existing_rows = (
            db.query(ReceiptItem)
            .filter(ReceiptItem.submission_id == req.receiptId)
            .order_by(ReceiptItem.seq_no.asc())
            .all()
        )
        if len(existing_rows) != len(documents):
            db.query(ReceiptItem).filter(ReceiptItem.submission_id == req.receiptId).delete(synchronize_session=False)
            for idx, d in enumerate(documents, start=1):
                db.add(
                    ReceiptItem(
                        submission_id=req.receiptId,
                        seq_no=idx,
                        doc_type=d.get("docType", "RECEIPT"),
                        image_key=(d.get("imageKey") or "").strip(),
                        card_num=CARD_NUM_NO_CARD,
                        status="PENDING",
                    )
                )
        else:
            for idx, d in enumerate(documents, start=1):
                row = existing_rows[idx - 1]
                row.seq_no = idx
                row.doc_type = d.get("docType", "RECEIPT")
                row.image_key = (d.get("imageKey") or "").strip()
                row.status = "PENDING"
                row.error_code = None
                row.error_message = None
        submission.status = "VERIFYING"
        submission.updated_at = datetime.utcnow()
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

        # 2) 자식 테이블 개별 저장 (placeholder row 업데이트)
        mapped_items, _ = map_ocr_to_db(req.receiptId, ocr_assets, documents)
        item_rows = (
            db.query(ReceiptItem)
            .filter(ReceiptItem.submission_id == req.receiptId)
            .order_by(ReceiptItem.seq_no.asc())
            .all()
        )
        if len(item_rows) != len(mapped_items):
            # 이론상 발생하지 않아야 하나, 안전하게 재구성
            db.query(ReceiptItem).filter(ReceiptItem.submission_id == req.receiptId).delete(synchronize_session=False)
            for item in mapped_items:
                db.add(item)
            item_rows = mapped_items
        else:
            for i, mapped in enumerate(mapped_items):
                row = item_rows[i]
                row.doc_type = mapped.doc_type
                row.image_key = mapped.image_key
                row.store_name = mapped.store_name
                row.biz_num = mapped.biz_num
                row.pay_date = mapped.pay_date
                row.amount = mapped.amount
                row.address = mapped.address
                row.location = mapped.location
                row.card_num = mapped.card_num
                row.status = mapped.status
                row.error_code = mapped.error_code
                row.error_message = mapped.error_message
                row.confidence_score = mapped.confidence_score
                row.ocr_raw = mapped.ocr_raw
                row.parsed = mapped.parsed

        def mark_item(i: int, code: Optional[str]) -> None:
            """code 기준으로 status / error_code / error_message 를 일관 설정."""
            status, normalized_code, msg = _resolve_item_status_error(code)
            ocr_assets[i]["status"] = status
            ocr_assets[i]["error_code"] = normalized_code
            item_rows[i].status = status
            item_rows[i].error_code = normalized_code
            item_rows[i].error_message = msg

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
                        mark_item(i, "BIZ_010")
            else:
                ri = receipt_idx[0]
                rp = ocr_assets[ri]["parsed"]
                ocr_amount = rp.get("amount")
                amount = ocr_amount
                pay_date = rp.get("payDate") or ""
                store_name = rp.get("storeName") or ""
                address = rp.get("address") or ""
                location = rp.get("location") or ""
                biz_num = _normalize_biz_num(rp.get("businessNum"))
                card_num = _normalize_card_num(rp.get("cardNum"))
                confidence = rp.get("confidenceScore") if isinstance(rp.get("confidenceScore"), int) else 0

                # OCR 신뢰도가 낮으면 사용자 입력을 참조값으로 사용 (고신뢰 OCR은 그대로 우선)
                user_amt, user_pd, user_loc = _get_user_input_for_document(req.data, ri)
                if confidence < OCR_CONFIDENCE_THRESHOLD and user_amt is not None:
                    amount = user_amt
                    pay_date = user_pd or pay_date
                    location = user_loc or location
                    rp["amount"] = amount
                    rp["payDate"] = pay_date
                    rp["location"] = location
                    item_rows[ri].amount = _normalize_amount(amount) if _normalize_amount(amount) is not None else amount
                    item_rows[ri].pay_date = _normalize_pay_date_for_storage(pay_date) or _normalize_pay_date_canonical(pay_date) or pay_date
                    item_rows[ri].location = _normalize_location(location)

                if ocr_assets[ri]["status"] == "ERROR_OCR":
                    fail_code = "ERROR_OCR"
                elif amount is None:
                    mark_item(ri, "OCR_001")
                    fail_code = "ERROR_OCR"
                else:
                    _, normalized_date = _normalize_and_validate_2026_date(pay_date)
                    pay_date_stored = normalized_date or _normalize_pay_date_canonical(pay_date) or pay_date
                    item_rows[ri].pay_date = _normalize_pay_date_for_storage(pay_date_stored) or pay_date_stored
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
                            min_amount_stay=min_amount_stay,
                            min_amount_tour=min_amount_tour,
                        )
                        if fc:
                            if fc == "OCR_003":
                                ocr_raw_ri = ocr_assets[ri].get("ocrRaw")
                                if _classifier_is_forbidden(store_name, address, ocr_raw_ri):
                                    item_fail = "BIZ_008"
                                else:
                                    pred_cat, conf, ctype = classify_store(
                                        store_name, address, ocr_raw_ri, use_gemini=use_gemini_classifier
                                    )
                                    should_auto_register = (
                                        unknown_store_policy == "AUTO_REGISTER"
                                        and bool(pred_cat)
                                        and conf >= auto_register_threshold
                                    )
                                    if should_auto_register:
                                        _auto_register_store(
                                            db,
                                            req.receiptId,
                                            store_name or "",
                                            address,
                                            biz_num,
                                            _extract_store_tel(ocr_raw_ri or {}),
                                            pred_cat,
                                            conf,
                                            ctype,
                                        )
                                        # 자동 상점추가 후에는 검수 대기 없이 FIT. 데이터 자산화(master_stores + unregistered_stores) 완료.
                                        # item_fail 유지 None → 아래 FIT 처리
                                    else:
                                        _register_new_candidate_store(
                                            db, req.receiptId, rp, ocr_raw_ri,
                                            predicted_category=pred_cat or None,
                                            category_confidence=conf if conf else None,
                                            classifier_type=ctype,
                                        )
                                        item_fail = "PENDING_NEW"
                            else:
                                item_fail = fc
                    if not item_fail and _check_duplicate_receipt_item(
                        db, req.receiptId, biz_num, pay_date_stored, amount, card_num
                    ):
                        item_fail = "BIZ_001"
                    if not item_fail and req.campaignId:
                        # OCR 결과 기반 캠페인 자동 선택(확장)
                        selected_campaign_id = _resolve_campaign_id_for_receipt(
                            db, req.type, location, pay_date_stored
                        )
                        if selected_campaign_id and submission.campaign_id != selected_campaign_id:
                            submission.campaign_id = selected_campaign_id
                        ok, c_fail = validate_campaign_rules(
                            db, int(submission.campaign_id or DEFAULT_CAMPAIGN_ID), location, pay_date_stored
                        )
                        if not ok and c_fail:
                            item_fail = c_fail

                    # 사용자 입력 대비 OCR 금액 10% 이상 차이 시 수동검증 보류
                    if not item_fail and user_amt is not None:
                        base_amount = ocr_amount if isinstance(ocr_amount, int) else amount
                        if _is_amount_mismatch(user_amt, base_amount):
                            item_fail = "PENDING_VERIFICATION"

                    # 인식 불량(상점명·사업자번호·주소 누락 또는 저신뢰도) → 수동 검수(보정) 유도
                    if not item_fail and _should_require_manual_review_for_low_quality(
                        store_name, biz_num, address, confidence
                    ):
                        item_fail = "OCR_004"

                    if item_fail:
                        mark_item(ri, item_fail)
                        fail_code = item_fail
                    else:
                        mark_item(ri, None)
                        total_amount = amount

                if ota_idx:
                    oi = ota_idx[0]
                    if fail_code and total_amount <= 0:
                        if ocr_assets[oi]["status"] == "PENDING":
                            mark_item(oi, fail_code)
                    elif ocr_assets[oi]["status"] == "ERROR_OCR":
                        fail_code = fail_code or (ocr_assets[oi]["error_code"] or "OCR_001")
                    else:
                        op = ocr_assets[oi]["parsed"]
                        ota_amount = op.get("amount")
                        if total_amount and ota_amount is not None and ota_amount != total_amount:
                            mark_item(oi, "BIZ_011")
                            fail_code = fail_code or "BIZ_011"
                        else:
                            mark_item(oi, None)
                            audit_lines.append(f"영수증 금액({total_amount}) = 명세서 금액({ota_amount}) 일치")

        else:  # TOUR
            receipt_idx = [i for i, a in enumerate(ocr_assets) if a["docType"] == "RECEIPT"]
            if len(receipt_idx) < 1 or len(receipt_idx) > 3:
                fail_code = "BIZ_010"
                for i, a in enumerate(ocr_assets):
                    if a["status"] == "PENDING":
                        mark_item(i, "BIZ_010")
            else:
                total = 0
                amount_parts: List[str] = []
                # 동일 제출건 내 중복: 동일 (사업자번호, 결제일, 금액, 카드) 조합은 1매만 FIT, 나머지는 UNFIT_DUPLICATE
                seen_fit_key: set = set()
                for i in receipt_idx:
                    a = ocr_assets[i]
                    p = a["parsed"]
                    amount = _normalize_amount(p.get("amount"))
                    pay_date = p.get("payDate") or ""
                    store_name = _normalize_store_name(p.get("storeName"))
                    address = _normalize_address((p.get("address") or "").strip()) or ""
                    location = _normalize_location(p.get("location"))
                    biz_num = _normalize_biz_num(p.get("businessNum"))
                    card_num = _normalize_card_num(p.get("cardNum"))
                    is_2026, norm_date = _normalize_and_validate_2026_date(pay_date)
                    pay_date_stored = _normalize_pay_date_for_storage(norm_date or _normalize_pay_date_canonical(pay_date) or pay_date) or (norm_date or _normalize_pay_date_canonical(pay_date) or pay_date)

                    if a["status"] == "ERROR_OCR":
                        continue
                    if amount is None:
                        mark_item(i, "OCR_001")
                        continue

                    fit_key = (biz_num or "", pay_date_stored or "", amount or 0, card_num or "")
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
                            ocr_raw_a = a.get("ocrRaw")
                            if _classifier_is_forbidden(store_name, address, ocr_raw_a):
                                item_fail = "BIZ_008"
                            else:
                                pred_cat, conf, ctype = classify_store(
                                    store_name, address, ocr_raw_a, use_gemini=use_gemini_classifier
                                )
                                should_auto_register = (
                                    unknown_store_policy == "AUTO_REGISTER"
                                    and bool(pred_cat)
                                    and conf >= auto_register_threshold
                                )
                                if should_auto_register:
                                    _auto_register_store(
                                        db,
                                        req.receiptId,
                                        store_name or "",
                                        address,
                                        biz_num,
                                        _extract_store_tel(ocr_raw_a or {}),
                                        pred_cat,
                                        conf,
                                        ctype,
                                    )
                                    # 자동 상점추가 후에는 검수 대기 없이 FIT. 데이터 자산화(master_stores + unregistered_stores) 완료.
                                    # item_fail 유지 None → 아래 FIT 처리
                                else:
                                    _register_new_candidate_store(
                                        db, req.receiptId, p, ocr_raw_a,
                                        predicted_category=pred_cat or None,
                                        category_confidence=conf if conf else None,
                                        classifier_type=ctype,
                                    )
                                    item_fail = "PENDING_NEW"

                    # 타 제출건(FIT 확정 건)과 동일 영수증이면 중복 → 해당 장만 UNFIT (다른 장은 그대로 FIT 가능)
                    if not item_fail and _check_duplicate_receipt_item(
                        db, req.receiptId, biz_num, pay_date_stored, amount, card_num
                    ):
                        item_fail = "BIZ_001"
                    # 동일 제출건 내 중복(A/A/A): 동일 키는 1매만 FIT, 나머지는 UNFIT_DUPLICATE(전체 fail_code에는 반영 안 함)
                    if not item_fail and fit_key in seen_fit_key:
                        mark_item(i, "BIZ_001")
                        continue
                    if not item_fail and req.campaignId:
                        selected_campaign_id = _resolve_campaign_id_for_receipt(
                            db, req.type, location, pay_date_stored
                        )
                        if selected_campaign_id and submission.campaign_id != selected_campaign_id:
                            submission.campaign_id = selected_campaign_id
                        ok, c_fail = validate_campaign_rules(
                            db, int(submission.campaign_id or DEFAULT_CAMPAIGN_ID), location, pay_date_stored
                        )
                        if not ok and c_fail:
                            item_fail = c_fail

                    # 인식 불량(핵심 필드 누락 또는 저신뢰도) → 수동 검수(보정) 유도
                    if not item_fail:
                        conf = p.get("confidenceScore") if isinstance(p.get("confidenceScore"), int) else None
                        if _should_require_manual_review_for_low_quality(store_name, biz_num, address, conf):
                            item_fail = "OCR_004"

                    if item_fail:
                        mark_item(i, item_fail)
                        continue

                    mark_item(i, None)
                    total += amount
                    amount_parts.append(str(amount))
                    seen_fit_key.add(fit_key)

                total_amount = total
                user_total = _get_user_total_amount(req.data, len(receipt_idx))
                if user_total is not None and _is_amount_mismatch(user_total, total_amount):
                    for i in receipt_idx:
                        if ocr_assets[i].get("status") == "FIT":
                            mark_item(i, "PENDING_VERIFICATION")
                    fail_code = fail_code or "PENDING_VERIFICATION"
                if total_amount < min_amount_tour:
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

        # 4) 부모 상태 업데이트: total_amount는 반드시 item_rows FIT 합산으로 산출 (관리자 검증 정확도)
        total_amount = sum(it.amount or 0 for it in item_rows if it.status == "FIT")
        min_criteria = min_amount_stay if req.type == "STAY" else min_amount_tour
        # 1개 이상 영수증이 조건 충족(금액 기준 이상)이면 리워드 지급. 다른 장의 PENDING_NEW/PENDING_VERIFICATION으로 전체를 덮지 않음.
        condition_met = fit_cnt >= 1 and total_amount >= min_criteria
        if not condition_met:
            if not fail_code and pending_new_cnt > 0:
                fail_code = "PENDING_NEW"
            if not fail_code and pending_verification_cnt > 0:
                fail_code = "PENDING_VERIFICATION"
        audit_lines.append(
            f"총 {len(ocr_assets)}매 중 적격 {fit_cnt}매, 부적격 {unfit_cnt}매, 오류 {err_cnt}매, "
            f"신규상점대기 {pending_new_cnt}매, 수동검증대기 {pending_verification_cnt}매"
        )

        finalize_submission(submission, total_amount, min_criteria, fail_code)
        submission.audit_log = " | ".join(audit_lines) if audit_lines else (submission.fail_reason or "")
        submission.audit_trail = submission.audit_log
        db.commit()
        payload = _build_status_payload(submission, item_rows)
        await _send_result_callback(req.receiptId, payload, purpose="auto", actor="system")

    except Exception as e:
        logger.error("analyze_receipt_task failed: %s", e, exc_info=True)
        submission.status = "ERROR"
        submission.updated_at = datetime.utcnow()
        submission.total_amount = 0
        submission.fail_reason = str(e)
        submission.global_fail_reason = submission.fail_reason
        submission.audit_log = "complete 처리 중 예외 발생"
        submission.audit_trail = submission.audit_log
        db.commit()
        db.refresh(submission)
        item_rows_ex = (
            db.query(ReceiptItem)
            .filter(ReceiptItem.submission_id == req.receiptId)
            .order_by(ReceiptItem.seq_no.asc())
            .all()
        )
        payload = _build_status_payload(submission, item_rows_ex)
        await _send_result_callback(req.receiptId, payload, purpose="auto", actor="system")
    finally:
        db.close()