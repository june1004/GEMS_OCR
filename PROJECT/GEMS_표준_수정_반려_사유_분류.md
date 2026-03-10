# GEMS 표준 수정·반려 사유 분류 체계

지자체 담당자가 영수증 검수 시 겪는 오류 상황을 체계적으로 분류하고, **AI 학습 데이터(Sidecar JSON)** 로 자산화하기 위한 표준 수정 사유 리스트입니다.  
담당자 입력 피로도를 낮추기 위해 **카테고리별 프리셋** 형태로 제공하며, 각 사유의 `reason_code`는 AI 모델이 "왜 데이터가 불일치했는가"를 학습하는 **핵심 라벨**이 됩니다.

---

## 1. 금액 관련 수정 사유 (Amount Correction)

금액 미달·오인식 시 사용하며, 수정된 금액은 최종 승인 금액으로 관리됩니다.

| reason_code | 라벨 | 설명 | asset_tag |
|-------------|------|------|-----------|
| `ERR_OCR_AMOUNT` | OCR 인식 오류(금액) | 이미지 내 빛 반사·폰트 뭉개짐으로 AI가 숫자를 잘못 읽은 경우 | RE_TRAINING_REQUIRED |
| `ERR_UNIT_DECIMAL` | 단위/소수점 오인식 | 콤마(,)를 점(.)으로 인식하거나 원화 단위를 숫자로 오인한 경우 | RE_TRAINING_REQUIRED |
| `USER_AMOUNT_MISTAKE` | 사용자 입력 오기 | 시민이 영수증 금액을 실제와 다르게 수기 입력한 경우 (OCR이 정답) | USER_ERROR_LABEL |
| `AMOUNT_SUM_MISMATCH` | 합산 금액 불일치 | 할인 금액이 반영된 최종 결제액으로 교정하는 경우 | RE_TRAINING_REQUIRED |

---

## 2. 지역 및 가맹점 관련 사유 (Region & Merchant)

캠페인 대상 지역·업종 적합성 판단 시 사용합니다.

| reason_code | 라벨 | 설명 | asset_tag |
|-------------|------|------|-----------|
| `ERR_REGION_OCR` | 행정구역 오판독 | 가맹점 주소가 흐려 AI가 타 지역으로 분류했으나 실제는 대상 지역 | RE_TRAINING_REQUIRED |
| `CATEGORY_RECLASSIFY` | 업종 분류 교정 | OCR이 숙박업을 일반 음식점으로 잘못 분류 (STAY/TOUR 유형 변경) | RE_TRAINING_REQUIRED |
| `STORE_NAME_MISSING` | 상호명 누락/오류 | 상호명 잘림·특수문자로 인식 실패 시 담당자 수동 입력 | RE_TRAINING_REQUIRED |

---

## 3. 증거 이미지 품질 관련 사유 (Image Quality)

데이터 자산화 시 **학습 부적합 데이터**로 분류하기 위한 지표입니다.

| reason_code | 라벨 | 설명 | asset_tag |
|-------------|------|------|-----------|
| `IMAGE_BLUR` | 이미지 흐림(Blur) | 촬영 흔들림으로 인간은 식별 가능하나 AI 분석 실패 | LOW_QUALITY_SAMPLE |
| `IMAGE_CROP` | 영수증 잘림(Crop) | 일시·금액·가맹점 등 필수 정보가 프레임 밖으로 나간 경우 | LOW_QUALITY_SAMPLE |
| `DUPLICATE_SUSPECT` | 중복 제출 의심 | 동일 영수증 이미지가 다른 ID로 제출·Hash 일치 | FRAUD_CHECK |

---

## 4. 기타

| reason_code | 라벨 | 설명 |
|-------------|------|------|
| `OTHER` | 기타 (직접 입력) | 위 사유에 해당하지 않는 경우. 상세는 담당자 입력값 사용 |

---

## 5. 관리자 설정 기반 필드 제어 시나리오

검수자 업무 과중 방지를 위해, **캠페인 유형에 따라 편집 가능 필드를 가변 활성화**합니다.

| 캠페인 유형 | 활성화 필드 (Editable Fields) | 주요 활용 사유 |
|-------------|-------------------------------|----------------|
| **숙박형 (STAY)** | 결제 금액, 가맹점 주소, 숙박 일수 | 금액 미달·지역 외 영수증 교정 |
| **소비형 (TOUR)** | 결제 금액, 업종 카테고리 | 업종 부적합·금액 오기재 교정 |
| **통합형 (ALL)** | 모든 OCR 추출 필드 | AI 성능 고도화를 위한 전수 교정 |

- FE에서는 **환경설정 → 검수 옵션**에서 “금액 수정 활성화”, “주소/지역 수정 활성화” 등으로 제어합니다.
- BE에서 캠페인별로 `editable_fields` 등을 내려주면, 해당 필드만 교정 패널에 노출하도록 확장 가능합니다.

---

## 6. 수정 데이터 자산화 구조 (Sidecar JSON)

담당자가 사유를 선택하고 저장하면, 보안 스토리지 내 JSON에 아래와 같이 기록됩니다.

```json
{
  "receipt_id": "uuid-1234",
  "ai_result": { "amount": 45000, "confidence": 0.65 },
  "human_correction": {
    "final_amount": 65000,
    "reason_code": "ERR_OCR_AMOUNT",
    "reason_desc": "빛 반사로 인한 천 단위 인식 오류 교정",
    "reviewed_by": "admin_01",
    "at": "2026-03-05T12:00:00Z"
  },
  "asset_tag": "RE_TRAINING_REQUIRED"
}
```

- **reason_code**: 위 표준 코드 사용 시 AI 재학습 시 “왜 불일치했는가” 라벨로 활용됩니다.
- **asset_tag**: `RE_TRAINING_REQUIRED`(재학습 필요), `USER_ERROR_LABEL`(사용자 오류), `LOW_QUALITY_SAMPLE`(저품질 샘플), `FRAUD_CHECK`(부정 검수) 등으로 학습 데이터셋 분류에 사용합니다.

이 구조는 영수증 승인 프로세스를 넘어 **지자체 독자 OCR 교정 모델**을 만드는 핵심 자산이 됩니다.
