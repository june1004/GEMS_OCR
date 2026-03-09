# 업종 자동 분류 (Smart Classifier)
# Step 1: 룰 기반 blacklist/whitelist
# Step 2: (선택) 시맨틱 유사도
# Step 3: (선택) Gemini API 문맥 추론
#
# Gemini 작동 조건 (모두 만족 시에만 호출):
#   1. 환경변수 GEMINI_API_KEY 가 비어 있지 않음
#   2. JudgmentRuleConfig.enable_gemini_classifier == True (관리자 설정)
#   3. classify_store(..., use_gemini=True) 로 호출됨
#   4. 룰 기반 결과가 불명확: (category 없음 또는 confidence < 0.5)
#   5. 입력 유효: store_name 또는 address 중 하나 이상 비어 있지 않음

import os
import re
import json
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# Gemini API 설정 (환경변수 우선)
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
# v1beta에서 gemini-1.5-flash는 404(모델 단종). gemini-2.0-flash 사용. 단종 시 gemini-2.5-flash 등으로 변경.
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-2.0-flash").strip()
if "1.5-flash" in (GEMINI_MODEL or ""):
    logger.warning(
        "GEMINI_MODEL=%s is deprecated/retired (404). Using gemini-2.0-flash. Set GEMINI_MODEL=gemini-2.0-flash in env.",
        GEMINI_MODEL,
    )
    GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_TIMEOUT_SEC = float(os.getenv("GEMINI_TIMEOUT_SEC", "12"))
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "32"))

# Blacklist: 포함 시 즉시 UNFIT_CATEGORY (BIZ_008)
FORBIDDEN_KEYWORDS = (
    "단란주점", "유흥주점", "유흥주점영업", "무도장", "사교춤장",
    "유흥", "단란", "주점", "노래방", "노래바", "마사지", "성인",
)

# Whitelist: 상호/주소/OCR 텍스트에 포함 시 해당 카테고리로 매핑 (신뢰도 0.85)
WHITELIST_KEYWORDS: dict = {
    "펜션": "STAY",
    "숙박": "STAY",
    "호텔": "STAY",
    "모텔": "STAY",
    "게스트하우스": "STAY",
    "식당": "TOUR_FOOD",
    "한식": "TOUR_FOOD",
    "음식점": "TOUR_FOOD",
    "맛집": "TOUR_FOOD",
    "박물관": "TOUR_SIGHTSEEING",
    "미술관": "TOUR_SIGHTSEEING",
    "체험마을": "TOUR_EXPERIENCE",
    "체험": "TOUR_EXPERIENCE",
    "카페": "TOUR_CAFE",
    "커피": "TOUR_CAFE",
    "디저트": "TOUR_CAFE",
    "베이커리": "TOUR_CAFE",
    "관광": "TOUR_SIGHTSEEING",
    "리조트": "STAY",
    "스키": "TOUR_SIGHTSEEING",
    "스키장": "TOUR_SIGHTSEEING",
}

CONFIDENCE_RULE_WHITELIST = 0.85
CONFIDENCE_RULE_BLACKLIST = 1.0
AUTO_REGISTER_THRESHOLD = 0.9


def _text_bundle(store_name: Optional[str], address: Optional[str], ocr_raw: Optional[dict]) -> str:
    """분류에 사용할 통합 텍스트."""
    parts = []
    if store_name:
        parts.append(store_name)
    if address:
        parts.append(address)
    if ocr_raw:
        try:
            parts.append(json.dumps(ocr_raw, ensure_ascii=False))
        except Exception:
            pass
    return " ".join(parts)


def is_forbidden(store_name: Optional[str], address: Optional[str], ocr_raw: Optional[dict]) -> bool:
    """Blacklist 키워드 포함 시 True (UNFIT_CATEGORY)."""
    text = _text_bundle(store_name, address, ocr_raw)
    return any(kw in text for kw in FORBIDDEN_KEYWORDS)


def classify_by_rules(
    store_name: Optional[str], address: Optional[str], ocr_raw: Optional[dict]
) -> Tuple[Optional[str], float, str]:
    """
    룰 기반만 사용. (카테고리, 신뢰도, classifier_type)
    - Blacklist 적발 시 (None, 1.0, "RULE") -> 호출측에서 UNFIT 처리
    - Whitelist 매칭 시 (category, 0.85, "RULE")
    - 없으면 (None, 0.0, "RULE")
    """
    if is_forbidden(store_name, address, ocr_raw):
        return None, CONFIDENCE_RULE_BLACKLIST, "RULE"

    text = _text_bundle(store_name, address, ocr_raw)
    for kw, category in WHITELIST_KEYWORDS.items():
        if kw in text:
            return category, CONFIDENCE_RULE_WHITELIST, "RULE"
    return None, 0.0, "RULE"


def is_gemini_available() -> Tuple[bool, str]:
    """
    Gemini API 호출 가능 여부. 헬스 체크·운영 확인용.
    반환: (가능 여부, 사유 문자열)
    """
    if not GEMINI_API_KEY:
        return False, "GEMINI_API_KEY not set"
    return True, "ok"


def classify_with_gemini(
    store_name: Optional[str], address: Optional[str]
) -> Tuple[Optional[str], float, str]:
    """
    Gemini API로 업종 추론.
    작동 조건: GEMINI_API_KEY 설정됨, store_name 또는 address 중 하나 이상 유효.
    반환: (category, confidence, "AI")
    """
    if not GEMINI_API_KEY:
        logger.debug("Gemini skip: GEMINI_API_KEY not set")
        return None, 0.0, "RULE"
    sn = (store_name or "").strip()
    addr = (address or "").strip()
    if not sn and not addr:
        logger.debug("Gemini skip: no store_name or address")
        return None, 0.0, "RULE"

    try:
        import httpx
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        prompt = (
            "다음 상점 정보만 보고, 업종을 다음 중 정확히 하나로만 분류해줘. "
            "답변은 반드시 한 줄로, 분류명만 출력해줘. (이유 없이)\n"
            "선택지: TOUR_FOOD, TOUR_CAFE, TOUR_SIGHTSEEING, TOUR_EXPERIENCE, STAY, EXCLUDED\n"
            f"상호명: {sn or '(없음)'}\n"
            f"주소: {addr or '(없음)'}\n"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": min(256, max(8, GEMINI_MAX_OUTPUT_TOKENS)),
            },
        }
        timeout = min(30.0, max(5.0, GEMINI_TIMEOUT_SEC))
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
        data = r.json()
        candidates = (data.get("candidates") or [{}])[0]
        parts = (candidates.get("content") or {}).get("parts") or []
        if not parts:
            logger.debug("Gemini response: no content parts")
            return None, 0.0, "RULE"
        raw = (parts[0].get("text") or "").strip().upper()
        for cat in ("TOUR_FOOD", "TOUR_CAFE", "TOUR_SIGHTSEEING", "TOUR_EXPERIENCE", "STAY", "EXCLUDED"):
            if cat in raw or cat.replace("_", " ") in raw:
                if "EXCLUDED" in raw:
                    return None, 0.85, "AI"
                logger.debug("Gemini classified: %s -> %s", (sn or addr)[:30], cat)
                return cat, 0.85, "AI"
        logger.debug("Gemini response: no matching category in %s", raw[:80])
        return None, 0.0, "RULE"
    except Exception as e:
        if getattr(e, "response", None) and getattr(e.response, "status_code", None) == 404:
            logger.warning(
                "Gemini model not found (404). GEMINI_MODEL=%s. Try GEMINI_MODEL=gemini-2.0-flash or see https://ai.google.dev/gemini-api/docs/models",
                GEMINI_MODEL,
            )
        else:
            logger.warning("Gemini classification failed: %s", e)
        return None, 0.0, "RULE"


def classify_store(
    store_name: Optional[str],
    address: Optional[str],
    ocr_raw: Optional[dict],
    use_gemini: bool = True,
) -> Tuple[Optional[str], float, str]:
    """
    하이브리드 분류: 룰 -> (불명확 시) Gemini.
    반환: (category, confidence, classifier_type)
    - category None + high confidence = blacklist(UNFIT)
    - category 있음 + confidence >= AUTO_REGISTER_THRESHOLD = 자동 편입 후보
    """
    category, conf, ctype = classify_by_rules(store_name, address, ocr_raw)
    if is_forbidden(store_name, address, ocr_raw):
        return None, CONFIDENCE_RULE_BLACKLIST, "RULE"
    if category and conf >= AUTO_REGISTER_THRESHOLD:
        return category, conf, ctype
    if (not category or conf < 0.5) and use_gemini:
        cat2, conf2, _ = classify_with_gemini(store_name, address)
        if cat2 and conf2 > conf:
            return cat2, conf2, "AI"
    return category, conf, ctype
