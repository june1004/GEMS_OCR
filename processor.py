"""
GEMS OCR 후처리 및 상점 매칭 서비스.
시군구 필터링 → 상호명 유사도(token_sort_ratio) → 비즈니스 로직 검증 → 캠페인 필터(지역·기간). DB 조회 최소화.
"""
import re
from datetime import datetime
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text
from rapidfuzz import fuzz

# 에러 코드 (PRD)
ERR_DATE = "BIZ_002"  # 2026년 아님
ERR_AMOUNT = "BIZ_003"  # 최소 금액 미달 또는 사용자 입력과 불일치
ERR_LOCATION = "BIZ_004"  # 강원도 외 지역
ERR_CAMPAIGN_EXPIRED = "BIZ_005"  # 캠페인 기간 아님
ERR_REGION_MISMATCH = "BIZ_006"  # 캠페인 대상 지역 아님
ERR_STORE = "OCR_003"  # 마스터 미등록 상점
ERR_INVALID_DATE = "OCR_002"  # 결제일 형식 오류

# 상호명 유사도 임계값 (오타·표기 차이 대비)
FUZZY_MATCH_THRESHOLD = 85


def extract_ocr_fields(ocr_data: dict) -> Optional[dict]:
    """
    Naver OCR 응답 JSON에서 핵심 필드 추출.
    금액은 ₩, 콤마, 원 등 제거 후 숫자만 추출.
    """
    try:
        result = (ocr_data.get("images") or [{}])[0].get("receipt") or {}
        result = result.get("result")
        if not result:
            return None
        store_info = result.get("storeInfo") or {}
        store_name = (store_info.get("name") or {}).get("text") or ""
        store_name = store_name.strip()
        addr_obj = store_info.get("address") or {}
        full_address = (addr_obj.get("text") or "").strip()
        pay_date = (result.get("paymentInfo") or {}).get("date") or {}
        pay_date = (pay_date.get("text") or "").strip()
        raw_price = (result.get("totalPrice") or {}).get("price") or {}
        raw_price = (raw_price.get("text") or "0").strip()
        ocr_amount = int(re.sub(r"[^0-9]", "", raw_price)) if raw_price else 0
        addr_parts = full_address.split()
        city_county = addr_parts[1] if len(addr_parts) > 1 else ""
        return {
            "store_name": store_name,
            "full_address": full_address,
            "pay_date": pay_date,
            "ocr_amount": ocr_amount,
            "city_county": city_county,
        }
    except (KeyError, TypeError, ValueError):
        return None


def match_store_in_master(
    db: Session, store_name: str, city_county: str
) -> Tuple[bool, Optional[int]]:
    """
    시군구 1차 필터 후 상호명 유사도(token_sort_ratio)로 매칭.
    반환: (매칭 여부, matched store_id 또는 None). store_id는 master_stores에 id 컬럼 있을 때만.
    """
    if not (store_name or "").strip():
        return False, None
    store_name = store_name.strip()
    city_county = (city_county or "").strip()
    try:
        if city_county:
            rows = db.execute(
                text(
                    "SELECT store_name FROM master_stores WHERE city_county = :city"
                ),
                {"city": city_county},
            ).fetchall()
        else:
            rows = db.execute(
                text("SELECT store_name FROM master_stores")
            ).fetchall()
        for (s_name,) in rows:
            if not s_name:
                continue
            s_name = s_name.strip()
            if s_name == store_name:
                return True, None
            if fuzz.token_sort_ratio(store_name, s_name) >= FUZZY_MATCH_THRESHOLD:
                return True, None
        return False, None
    except Exception:
        return False, None


def validate_and_match(
    db: Session,
    store_name: str,
    full_address: str,
    pay_date: str,
    ocr_amount: int,
    city_county: str,
    user_amount: int,
    campaign_type: str,
    is_2026_date: bool,
) -> Tuple[str, Optional[str]]:
    """
    비즈니스 로직 검증 + 마스터 상점 매칭.
    순서: 날짜(2026) → 금액(최소+입력일치) → 지역(강원) → 상점 매칭(시군+유사도 85%).
    반환: (status, fail_reason). status는 "FIT" 또는 "UNFIT".
    """
    # (1) 날짜: 2026년 영수증인지
    if not is_2026_date or not re.search(r"2026|26", pay_date or ""):
        return "UNFIT", ERR_DATE

    # (2) 금액: 최소 금액 + 사용자 입력값 일치
    min_limit = 60000 if campaign_type == "STAY" else 50000
    if ocr_amount < min_limit:
        return "UNFIT", ERR_AMOUNT
    if ocr_amount != user_amount:
        return "UNFIT", "BIZ_007"  # 입력 금액과 OCR 금액 불일치

    # (3) 지역: 강원 포함 여부
    if full_address and "강원" not in full_address:
        return "UNFIT", ERR_LOCATION

    # (4) 상점 매칭: 시군 필터 → token_sort_ratio 85% 이상
    matched, _ = match_store_in_master(db, store_name, city_county)
    if not matched:
        return "UNFIT", ERR_STORE

    return "FIT", None


def validate_campaign_rules(
    db: Session,
    campaign_id: int,
    store_city: str,
    pay_date_str: str,
) -> Tuple[bool, Optional[str]]:
    """
    영수증이 해당 캠페인의 조건(지역, 기간, 활성)에 맞는지 검증.
    store_city: OCR에서 추출한 시군(예: 춘천시, 속초시).
    pay_date_str: 정규화된 결제일 "YYYY-MM-DD".
    반환: (통과 여부, 실패 시 에러 코드 또는 메시지).
    """
    try:
        row = db.execute(
            text(
                "SELECT is_active, target_city_county, start_date, end_date FROM campaigns WHERE campaign_id = :cid"
            ),
            {"cid": campaign_id},
        ).fetchone()
    except Exception:
        return True, None  # campaigns 테이블 없거나 조회 실패 시 필터 스킵(기존 동작 유지)

    if not row:
        return True, None  # 캠페인 없으면 제한 없음

    is_active = getattr(row, "is_active", True)
    if is_active is False:
        return False, "BIZ_005 (비활성 캠페인)"

    # 기간 검증 (start_date, end_date 둘 다 있으면만 검사)
    start_date = getattr(row, "start_date", None)
    end_date = getattr(row, "end_date", None)
    if start_date is not None and end_date is not None and pay_date_str:
        try:
            receipt_date = datetime.strptime(pay_date_str.strip()[:10], "%Y-%m-%d").date()
            if not (start_date <= receipt_date <= end_date):
                return False, ERR_CAMPAIGN_EXPIRED
        except ValueError:
            return False, ERR_INVALID_DATE

    # 지역 검증: target_city_county가 있으면 상점 시군과 일치(또는 유연 매칭)
    target = (getattr(row, "target_city_county", None) or "").strip()
    if not target:
        return True, None  # NULL = 강원 전체

    store_city = (store_city or "").strip()
    # 정확 일치 또는 유연 매칭 (예: target "속초시", store_city "속초시" / "속초" 등)
    if store_city == target:
        return True, None
    if target in store_city or store_city in target:
        return True, None
    # 핵심 키워드만 포함해도 통과 (예: "속초시" vs "속초")
    target_key = target.replace("시", "").replace("군", "").strip()
    if target_key and (target_key in store_city or store_city.startswith(target_key)):
        return True, None

    return False, ERR_REGION_MISMATCH
