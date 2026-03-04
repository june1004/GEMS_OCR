# 회신: FE 폼 데이터 전송 및 OCR 비교·관리자 검수 흐름

안녕하세요.

“FE에서 폼 데이터를 보내고, OCR 데이터와 비교(OCR 우선)하여 unfit 시 관리자가 비교 검수 후 검수 완료해야 하는지”에 대해 답변드립니다.

---

## 요약

- **그런 흐름을 쓰고 싶다면** FE에서 **Complete 요청 시 `data`(폼 데이터)** 를 함께 보내면 됩니다.
- 이 경우 BE는 **OCR 데이터를 우선**하고, FE 입력과 불일치하면 **PENDING_VERIFICATION**으로 두어 **관리자 검수 대기**로 둡니다.
- 관리자는 **상세 조회 후 override API로 최종 판정(FIT/UNFIT 등)** 을 내려 **검수 완료**할 수 있습니다.
- 다만 **v1 권장**은 운영 단순화를 위해 **documents만 보내는 방식(documents-only)** 이며, 이 경우 위 “폼 vs OCR 비교·검수” 단계는 없고 OCR 결과만으로 자동 판정됩니다.

---

## 1. FE에서 폼 데이터를 보내는 경우 (data 사용)

- Complete 시 **`documents`** 와 함께 **`data`** (사용자가 입력한 금액·결제일·지역 등)를 보낼 수 있습니다.
- BE 동작:
  - **OCR을 우선**합니다. OCR 신뢰도가 높으면 **OCR 인식값만** 사용합니다.
  - OCR 신뢰도가 낮을 때만 FE `data`(금액·결제일·지역 등)를 **참조값**으로 사용합니다.
  - **FE 입력 금액과 OCR 금액이 10% 이상 차이** 나면 해당 건을 **PENDING_VERIFICATION**(수동 검증 대기)으로 두어, 관리자 검수 대기 상태로 둡니다.
- 따라서 “폼 데이터 전송 → OCR과 비교(OCR 우선) → 불일치 시 관리자 검수” 흐름은 **data를 보낼 때 이미 BE에 구현되어 있습니다.**

---

## 2. unfit인 경우 “비교하여 검수 완료”하는 방법

- **PENDING_VERIFICATION**, **PENDING_NEW**, **UNFIT** 등으로 나온 건은 **관리자 검수 대상**입니다.
- 관리자는 다음으로 **비교·검토 후 검수 완료**할 수 있습니다.
  1. **상세 조회**: `GET /api/v1/admin/submissions/{receiptId}`  
     - 응답에 `items[].extracted_data`(OCR 기반), `items[].ocr_raw`, `audit_trail` 등이 포함됩니다.  
     - (FE에서 data를 보냈다면, 별도 저장 경로가 있다면 그 값과 비교 가능합니다. 현재 스펙상 “FE 입력값”이 응답에 직접 필드로 포함되지는 않으며, 관리자는 OCR 결과·audit_trail·에러 사유 등을 보고 판단합니다.)
  2. **검수 완료(최종 판정)**: `POST /api/v1/admin/submissions/{receiptId}/override`  
     - `status`: `FIT` 또는 `UNFIT` 등 최종 판정  
     - `reason`: 검수 사유 (감사용)  
     - 필요 시 `resend_callback: true` 로 FE에 결과 재전송  
- 즉, **“unfit인 경우 비교하여 검수 완료”** 는 **override API로 최종 판정을 내리는 것**으로 수행합니다. OCR 데이터(및 필요 시 FE 쪽에서 보낸 data)를 기준으로 관리자가 판단한 뒤, override로 검수 완료하는 구조입니다.

---

## 3. 정리

| 구분 | 내용 |
|------|------|
| FE 폼 데이터 전송 | Complete 시 `data`에 사용자 입력값(금액 등)을 넣어 보내면 됨. (선택) |
| OCR 우선 여부 | **OCR 우선.** 신뢰도 높으면 OCR만 사용, 낮을 때만 FE data 참조. |
| 불일치 시 | FE 입력 vs OCR 금액 10% 이상 차이 → **PENDING_VERIFICATION** → 관리자 검수 대기. |
| 관리자 검수 완료 | Admin이 상세 조회 후 **override** API로 FIT/UNFIT 등 최종 판정 = 검수 완료. |
| v1 권장 | 운영 단순화를 위해 **documents만 전송(documents-only)** 권장. 이 경우 위 “폼 vs OCR 비교·검수” 단계는 없음. |

요청하신 “FE에서 폼 데이터를 보내고, OCR과 비교(OCR 우선)하여 unfit인 경우 관리자가 비교하여 검수 완료”하는 흐름은, **data를 사용하는 연동**으로 가능하며, 관리자 검수 완료는 **override API**로 수행하시면 됩니다.

추가로 궁금하신 점 있으시면 말씀해 주세요.

감사합니다.
