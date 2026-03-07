# 업종 자동 분류 — Gemini API 연동 가이드

> 신규 상점 후보의 업종을 룰(키워드)으로 분류할 수 없을 때 **Gemini API**로 문맥 추론을 수행합니다.  
> 아래 **작동 조건**을 모두 만족할 때만 API가 호출됩니다.

---

## 1. Gemini 작동 조건 (체크리스트)

다음 **다섯 가지**를 모두 만족해야 실제로 Gemini가 호출됩니다.

| # | 조건 | 확인 방법 |
|---|------|-----------|
| 1 | **환경변수 `GEMINI_API_KEY`** 가 비어 있지 않음 | `GET /api/health` → `gemini_configured: true` |
| 2 | **JudgmentRuleConfig.enable_gemini_classifier** = True | 관리자 규칙 설정 API/화면에서 "Gemini 분류 사용" ON |
| 3 | **분류 흐름**에서 `classify_store(..., use_gemini=True)` 로 호출됨 | BE: TOUR/STAY 신규 상점 판단 시 rule_cfg 기반 전달 (기본 True) |
| 4 | **룰 기반 결과가 불명확**: 카테고리 없음 또는 confidence < 0.5 | 룰만으로는 업종 결정 불가 시에만 Gemini 시도 |
| 5 | **입력 유효**: `store_name` 또는 `address` 중 하나 이상 존재 | 둘 다 비어 있으면 API 호출 생략 (비용·에러 방지) |

- **1번 미충족**: 룰 기반 분류만 동작, Gemini 호출 없음.  
- **2번 OFF**: 관리자가 Gemini 비활성화한 경우, 호출 없음.  
- **4번 불충족**: 룰로 이미 충분히 분류된 경우(예: whitelist 매칭), Gemini 호출 없음.  
- **5번 불충족**: 상호명·주소가 모두 없으면 호출하지 않음.

---

## 2. 환경 설정

### 2.1 API 키

1. [Google AI Studio](https://aistudio.google.com/app/apikey)에서 API 키 발급.
2. 서버 환경변수에 추가:
   ```bash
   export GEMINI_API_KEY="your-api-key"
   ```
   `.env` 사용 시:
   ```
   GEMINI_API_KEY=your-api-key
   ```
3. **적용 여부 확인**: `GET /api/health` 응답의 `gemini_configured` 가 `true` 이면 키가 설정된 상태입니다.

### 2.2 선택 환경변수

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `GEMINI_API_KEY` | (필수) | Google AI Studio에서 발급한 API 키. 없으면 Gemini 미호출. |
| `GEMINI_MODEL` | `gemini-2.0-flash` | 사용할 모델명 (예: `gemini-1.5-flash`, `gemini-2.0-flash`). |
| `GEMINI_TIMEOUT_SEC` | `12` | API 요청 타임아웃(초). 5~30 사이로 적용. |
| `GEMINI_MAX_OUTPUT_TOKENS` | `32` | 최대 출력 토큰 수. 8~256 사이로 적용. |

---

## 3. 동작 흐름

1. **Step 1 (Rule)**  
   Blacklist(유흥·단란주점 등) → 즉시 제외.  
   Whitelist(펜션·식당·카페 등) → 카테고리 할당(신뢰도 0.85).
2. **Step 2 (Semantic)**  
   (선택) 시맨틱 유사도 — 현재 미구현, 확장 시 `classify_store` 내부에서 호출.
3. **Step 3 (AI)**  
   **위 작동 조건 1~5를 모두 만족할 때만** Gemini로 상호명·주소 기반 업종 추론.

분류 신뢰도가 **0.9 이상**이면 해당 상점을 `master_stores`에 자동 편입(`AUTO_REGISTERED`) 후보로 두며, 정책에 따라 FIT 처리·관리자 검토 대상으로 노출됩니다.

---

## 4. API 호출 형식 (참고)

`store_classifier.classify_with_gemini()` 내부:

- **Endpoint**: `https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={API_KEY}`
- **Method**: POST, JSON body.
- **Prompt 요지**: 상호명·주소만 보고 업종을 다음 중 하나로만 분류, 한 줄로 분류명만 출력.  
  선택지: `TOUR_FOOD`, `TOUR_CAFE`, `TOUR_SIGHTSEEING`, `TOUR_EXPERIENCE`, `STAY`, `EXCLUDED`
- **응답 파싱**: `candidates[0].content.parts[0].text` 에서 분류명 추출.  
  `EXCLUDED` → 제외, 그 외 → 해당 카테고리(신뢰도 0.85, classifier_type `"AI"`).

---

## 5. 운영·점검

- **Gemini가 호출되는지 확인**  
  - 조건 1: `GET /api/health` → `gemini_configured: true`  
  - 조건 2: 관리자 규칙 설정에서 "Gemini 분류 사용" ON  
  - 조건 4·5: 룰로 불명확하고, 상호명 또는 주소가 있는 건만 호출됨.
- **코드에서 가용 여부 확인**  
  - `store_classifier.is_gemini_available()` → `(bool, reason)` 반환.  
  - 키가 없으면 `(False, "GEMINI_API_KEY not set")`.
- **실패 시**  
  - API 키 만료·할당량·네트워크 오류 시 `classify_with_gemini`가 예외를 잡고 `(None, 0.0, "RULE")` 반환.  
  - 로그에 `Gemini classification failed: ...` 출력.  
  - 이 경우 해당 건은 룰 결과만 사용(또는 PENDING_NEW 등 정책에 따름).

---

## 6. 지자체별 금지 업종 설정 (확장)

현재 Blacklist는 `store_classifier.FORBIDDEN_KEYWORDS`에 하드코딩되어 있습니다.  
지자체별로 다른 기준을 쓰려면:

- **옵션 A**: 환경변수로 키워드 목록 전달 후 파싱 (예: `FORBIDDEN_KEYWORDS_EXTRA=키워드1,키워드2`).
- **옵션 B**: DB 테이블 `classifier_config` (region_code, forbidden_keywords JSON, whitelist JSON) 추가 후, 분류 시 region(시군) 기준으로 조회해 적용.

원하시면 옵션 B용 마이그레이션·조회 로직 설계안을 별도 문서로 정리할 수 있습니다.

---

## 7. Self-Learning (피드백 루프)

관리자가 후보 상점의 카테고리를 수동 수정하면, 그 (상호·주소·최종 카테고리) 조합을 수집해:

- 주기적으로 Gemini fine-tuning용 데이터로 내보내거나,
- 룰 whitelist에 패턴을 추가하는 방식으로 정확도를 높일 수 있습니다.  
현재 코드에는 미구현이며, 추후 `unregistered_stores`의 `predicted_category` vs 관리자 확정 카테고리 비교·수집 로직을 추가하면 됩니다.

---

*문서 버전: 2.0 | GEMS OCR BE 기준 | Gemini 작동 조건 구체화·고도화*
