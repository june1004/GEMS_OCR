# 업종 자동 분류 — Gemini API 연동 가이드

> 신규 상점 후보의 업종을 룰(키워드)으로 분류할 수 없을 때 **Gemini API**로 문맥 추론을 수행합니다.  
> `store_classifier.py`에서 `GEMINI_API_KEY` 환경변수가 설정된 경우에만 호출됩니다.

---

## 1. 환경 설정

1. [Google AI Studio](https://aistudio.google.com/app/apikey)에서 API 키 발급.
2. 서버 환경변수에 추가:
   ```bash
   export GEMINI_API_KEY="your-api-key"
   ```
   `.env` 사용 시:
   ```
   GEMINI_API_KEY=your-api-key
   ```
3. 키가 없으면 **룰 기반 분류만** 동작하며, Gemini 호출은 건너뜁니다.

---

## 2. 동작 흐름

1. **Step 1 (Rule)**: Blacklist(유흥·단란주점 등) → 즉시 제외. Whitelist(펜션·식당·카페 등) → 카테고리 할당.
2. **Step 2 (Semantic)**: (선택) 시맨틱 유사도 매칭 — 현재는 미구현, 확장 시 `store_classifier.classify_store` 내부에서 호출.
3. **Step 3 (AI)**: 룰로 분류가 불명확할 때 **Gemini 2.0 Flash**로 상호명·주소 기반 업종 추론.

분류 신뢰도가 **0.9 이상**이면 해당 상점을 `master_stores`에 자동 편입(`AUTO_REGISTERED`)하여 당장 영수증을 FIT 처리하고, 관리자 리스트에는 '검토 필요'로 노출됩니다.

---

## 3. API 호출 형식 (참고)

`store_classifier.classify_with_gemini()` 내부에서는 아래와 같이 호출합니다.

- **Endpoint**: `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={API_KEY}`
- **Method**: POST, JSON body.
- **Prompt 예시** (실제 코드와 동일한 의도):
  ```
  다음 상점 정보만 보고, 업종을 다음 중 정확히 하나로만 분류해줘. 답변은 반드시 한 줄로, 분류명만 출력해줘. (이유 없이)
  선택지: TOUR_FOOD, TOUR_CAFE, TOUR_SIGHTSEEING, TOUR_EXPERIENCE, STAY, EXCLUDED
  상호명: 속초 아바이 마을 쉼터
  주소: 강원도 속초시 청호로 ...
  ```
- **응답**: `candidates[0].content.parts[0].text`에서 분류명 문자열 파싱 (EXCLUDED 또는 TOUR_* / STAY).

---

## 4. 지자체별 금지 업종 설정 (확장)

현재 Blacklist는 `store_classifier.FORBIDDEN_KEYWORDS`에 하드코딩되어 있습니다.  
지자체별로 다른 기준을 쓰려면:

- **옵션 A**: 환경변수로 키워드 목록 전달 후 파싱 (예: `FORBIDDEN_KEYWORDS_EXTRA=키워드1,키워드2`).
- **옵션 B**: DB 테이블 `classifier_config` (region_code, forbidden_keywords JSON, whitelist JSON) 추가 후, 분류 시 region(시군) 기준으로 조회해 적용.

원하시면 옵션 B용 마이그레이션·조회 로직 설계안을 별도 문서로 정리할 수 있습니다.

---

## 5. Self-Learning (피드백 루프)

관리자가 후보 상점의 카테고리를 수동 수정하면, 그 (상호·주소·최종 카테고리) 조합을 수집해:

- 주기적으로 Gemini fine-tuning용 데이터로 내보내거나,
- 룰 whitelist에 패턴을 추가하는 방식으로 정확도를 높일 수 있습니다.  
현재 코드에는 미구현이며, 추후 `unregistered_stores`의 `predicted_category` vs 관리자 확정 카테고리 비교·수집 로직을 추가하면 됩니다.

---

*문서 버전: 1.0 | GEMS OCR BE 기준*
