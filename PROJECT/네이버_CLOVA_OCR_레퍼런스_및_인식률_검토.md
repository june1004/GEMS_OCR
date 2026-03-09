# 네이버 CLOVA OCR API 레퍼런스 및 인식률 검토

> 레퍼런스: [CLOVA OCR 가이드](https://guide.ncloud-docs.com/docs/clovaocr-example01), [Document OCR - Receipt API](https://api.ncloud-docs.com/docs/ai-application-service-ocr-ocrdocumentocr-receipt)

---

## 1. API 요약

| 항목 | 내용 |
|------|------|
| **엔드포인트** | `POST {Invoke URL}/document/receipt` |
| **인증** | 헤더 `X-OCR-SECRET`: Secret Key |
| **요청 형식** | `application/json`(Base64 이미지) 또는 **multipart/form-data**(바이너리) |
| **버전** | V2 사용 필수 |

### 1.1 multipart/form-data 요청 (현재 구현 방식)

- **message** (JSON): `version`, `requestId`, `timestamp`, `images` 배열
  - `images[]`: `format`(jpg/jpeg/png), `name` 필수
- **file**: 실제 이미지 바이너리

현재 코드는 위 형식과 동일하게 구현되어 있음.

### 1.2 이미지 권장 사양 (공식)

| 항목 | 권장/제한 |
|------|-----------|
| **파일 크기** | 50MB 이하 |
| **형식** | jpg, jpeg, png, pdf, tif, tiff |
| **해상도** | A4 기준 150dpi 이상, **장축 기준 1960px 이하 권장** |
| **회전** | 45도 이상 기울어지면 인식률 저하 가능 |

---

## 2. STAY / TOUR 모델 분기 (인식률 향상)

FE 변경 없이 **저장 경로(Prefix)**로 OCR 도메인을 자동 분기합니다.

| 구분 | STAY | TOUR |
|------|------|------|
| **용도** | 숙박(일반 모델·인보이스/명세서) | 여행(영수증 특화 모델) |
| **문서 구성** | **영수증 1매 + 인보이스 1매** (최대 2매) | **영수증 최대 3매** |
| **MinIO 경로** | `STAY/receipts/...` | `TOUR/receipts/...` |
| **환경 변수** | `NAVER_OCR_STAY_INVOKE_URL`, `NAVER_OCR_STAY_SECRET` | `NAVER_OCR_TOUR_INVOKE_URL`, `NAVER_OCR_TOUR_SECRET` |
| **Fallback** | 미설정 시 `NAVER_OCR_INVOKE_URL`/`NAVER_OCR_SECRET` 사용 | 동일 |

- **Presigned URL**: 요청 시 이미 전달되는 `type`(STAY|TOUR)으로 object key를 `{type}/receipts/{receiptId}_{uuid}_{fileName}` 형태로 발급 → MinIO에 STAY/ 또는 TOUR/ 폴더로 저장.
- **OCR 호출**: `image_key`가 `STAY/` 또는 `TOUR/`로 시작하면 해당 도메인 URL/Secret로 요청; 기존 경로(prefix 없음)는 `project_type`(Complete 요청의 type) 또는 기본 TOUR 사용.
- **STAY 템플릿**: 네이버 클라우드 콘솔에서 STAY 도메인(일반 모델)에 **템플릿**을 등록하면 인식률 향상. 여러 템플릿 시 요청에 `templateIds` 추가 가능(확장).

---

## 2-1. STAY 템플릿 적용 전: TOUR와 동일한 Document Receipt 사용 절차

STAY에서도 TOUR와 같은 **Document OCR - Receipt** API를 쓰려면, 네이버 클라우드에서 **한 개의 Document Receipt 도메인**만 쓰고, 그 Invoke URL·Secret을 STAY/TOUR 모두에 넣으면 됩니다. (도메인명·도메인코드는 콘솔에서 도메인 생성 시 입력하는 값입니다.)

### Step 1. 네이버 클라우드 콘솔 접속

1. [네이버 클라우드 플랫폼](https://www.ncloud.com/) 로그인
2. **Console** → **AI·Application Service** → **CLOVA OCR** 이동  
   (또는 **Services** → **AI Services** → **CLOVA OCR**)

### Step 2. 특화 모델 신청 (영수증)

1. CLOVA OCR 메뉴에서 **특화 모델 설정** → **특화 모델 신청**
2. **영수증(KR)** 특화 모델 선택
3. 사용 목적·사용 시기·예상 사용량·상세 내용 입력 후 신청
4. 승인 후 **상태: 승인** 확인 (승인까지 일정 기간 소요될 수 있음)

### Step 3. 도메인 생성 (Document Receipt용)

1. **도메인 생성** 클릭
2. **특화 모델** 선택 후 다음 정보 입력:
   - **도메인명**: 예) `GEMS-RECEIPT`, `영수증-Production` 등 (콘솔에서 보이는 이름)
   - **도메인코드**: 예) `gems-receipt`, `receipt-prod` 등 (API 연동 시 식별용, 영문·숫자·하이픈 권장)
3. **인식 모델**: **영수증(KR)** 선택
4. 서비스 플랜 선택 (Basic / Standard / Advanced) 후 **도메인 생성** 완료

> **도메인명**과 **도메인코드**는 나중에 콘솔 목록에서 해당 도메인을 구분할 때 사용합니다. BE 환경 변수에는 넣지 않고, **Invoke URL**과 **Secret Key**만 사용합니다.

### Step 4. Invoke URL·Secret Key 확인

1. 생성된 **도메인** 클릭
2. **Document OCR** 또는 **Text OCR** 메뉴에서:
   - **Secret Key**: **[생성]** 버튼으로 Secret Key 생성 후 복사
   - **Invoke URL**: **[자동 연동]**으로 API Gateway 연동 후 표시되는 **Invoke URL** 복사
3. **Document OCR - Receipt**를 쓰려면 Invoke URL이 아래 형태여야 합니다:
   - `https://xxxxx.apigw.ntruss.com/custom/v1/xxxxx/xxxxx/document/receipt`  
   URL 끝이 **`/document/receipt`**인지 확인. (`/infer`로 끝나면 General/Custom OCR용이라 400 발생 가능.)

### Step 5. BE 환경 변수 설정 (STAY = TOUR 동일 값)

**방법 A. 단일 설정 (STAY·TOUR 모두 같은 도메인)**  
STAY/TOUR 전용 변수를 비우고 공통만 설정하면, 두 타입 모두 같은 Document Receipt를 사용합니다.

```env
NAVER_OCR_INVOKE_URL=https://xxxxx.apigw.ntruss.com/custom/v1/xxxxx/xxxxx/document/receipt
NAVER_OCR_SECRET=발급받은_Secret_Key

# 아래는 설정하지 않음 (미설정 시 위 값이 STAY·TOUR 모두에 fallback)
# NAVER_OCR_STAY_INVOKE_URL=
# NAVER_OCR_STAY_SECRET=
# NAVER_OCR_TOUR_INVOKE_URL=
# NAVER_OCR_TOUR_SECRET=
```

**방법 B. STAY·TOUR에 같은 URL·Secret 명시**  
나중에 STAY만 다른 도메인(템플릿)으로 바꿀 때를 대비해, 지금은 TOUR와 동일하게 넣어 둘 수 있습니다.

```env
NAVER_OCR_INVOKE_URL=https://xxxxx.apigw.ntruss.com/custom/v1/xxxxx/xxxxx/document/receipt
NAVER_OCR_SECRET=발급받은_Secret_Key

# STAY도 같은 Document Receipt 사용 (템플릿 적용 전)
NAVER_OCR_STAY_INVOKE_URL=https://xxxxx.apigw.ntruss.com/custom/v1/xxxxx/xxxxx/document/receipt
NAVER_OCR_STAY_SECRET=위와_동일한_Secret_Key
NAVER_OCR_TOUR_INVOKE_URL=https://xxxxx.apigw.ntruss.com/custom/v1/xxxxx/xxxxx/document/receipt
NAVER_OCR_TOUR_SECRET=위와_동일한_Secret_Key
```

### Step 6. 배포·재기동 후 확인

1. 환경 변수 반영 후 서비스 재기동(또는 배포)
2. STAY 타입으로 영수증 한 건 전송
3. 서버 로그에서 Naver OCR 호출이 **200**으로 성공하는지 확인.  
   (이전에 `domain=STAY ... 400`이 나왔다면, URL을 `/document/receipt`로 맞춘 뒤 사라져야 함.)

---

**요약**

| 단계 | 내용 |
|------|------|
| 도메인명·도메인코드 | 콘솔에서 도메인 생성 시 입력. BE에는 사용하지 않고, Invoke URL·Secret만 사용 |
| Invoke URL | 반드시 **`/document/receipt`** 로 끝나는 URL 사용 (STAY 400 방지) |
| STAY = TOUR | `NAVER_OCR_STAY_*` 미설정 시 `NAVER_OCR_*` 가 STAY·TOUR 모두에 적용됨 |

나중에 STAY 전용 **템플릿(일반 모델)** 을 쓰려면, 네이버에서 STAY용 도메인을 따로 만들고 그때 `NAVER_OCR_STAY_INVOKE_URL` / `NAVER_OCR_STAY_SECRET` 만 해당 도메인으로 바꾸면 됩니다.

---

## 2-2. 실제 서비스 설정 (GEMS 콘솔 기준)

콘솔에 등록된 두 서비스와, **STAY에 영수증 모델 적용** 시 사용할 설정을 정리한 표입니다.

### STAY용 적용 요약 (영수증 모델)

| 항목 | STAY에 적용할 값 |
|------|------------------|
| **사용 도메인** | TOUR와 동일 — **GEMS_Receipt_Audit_Service** (서비스 ID 50152) |
| **도메인명** | GEMS_Receipt_Audit_Service |
| **도메인코드** | gems_receipt_audit_pro |
| **모델 타입** | 영수증(KR) |
| **BE 설정** | `NAVER_OCR_INVOKE_URL` / `NAVER_OCR_SECRET` 에 50152 도메인의 URL·Secret 입력. STAY 전용 변수(`NAVER_OCR_STAY_*`)는 비워 두면 STAY도 동일 도메인 사용. |

즉, **새 도메인을 만들지 않고** 기존 TOUR(50152) 도메인의 Invoke URL·Secret을 공통으로 쓰면 STAY도 영수증 모델이 적용됩니다.

**Q. STAY 전용 Invoke URL·Secret을 공란으로 두면 된다는 의미인가?**  
예. `NAVER_OCR_STAY_INVOKE_URL`, `NAVER_OCR_STAY_SECRET` 을 **설정하지 않거나 비워 두면** BE는 공통 설정(`NAVER_OCR_INVOKE_URL`, `NAVER_OCR_SECRET`)을 사용합니다. 공통에 50152 도메인 URL·Secret을 넣어 두면 STAY도 TOUR와 동일한 특화 영수증 모델(50152)을 사용합니다.

**Q. 나중에 STAY 템플릿(50660)이 준비되면 50660으로 돌아가는 방법은?**  
가능합니다. 50660 도메인에서 Invoke URL·Secret을 발급받은 뒤, **STAY 전용 변수만** 넣으면 됩니다. TOUR는 계속 공통(또는 `NAVER_OCR_TOUR_*`)으로 50152를 사용합니다.

| 시점 | STAY 동작 | 설정 방법 |
|------|-----------|-----------|
| **지금 (템플릿 미적용)** | TOUR와 동일한 영수증 모델(50152) 사용 | `NAVER_OCR_STAY_INVOKE_URL`, `NAVER_OCR_STAY_SECRET` **비워 둠** (또는 미설정) |
| **나중 (50660 템플릿 적용)** | STAY 전용 템플릿 모델(50660) 사용 | `NAVER_OCR_STAY_INVOKE_URL`, `NAVER_OCR_STAY_SECRET` 에 **50660 도메인의 URL·Secret** 설정. 배포/재기동 후 STAY만 50660으로 전환됨. |

코드에서는 `NAVER_OCR_STAY_*` 가 있으면 그 값을 쓰고, 없으면 공통 `NAVER_OCR_*` 를 쓰므로, **환경 변수만 바꾸면** 코드 수정 없이 STAY를 50660으로 전환할 수 있습니다.

### 현재 콘솔 구성

| 구분 | 서비스 ID | 서비스명(도메인명) | 도메인코드 | 모델 타입 | 비고 |
|------|-----------|-------------------|------------|-----------|------|
| **TOUR** | 50152 | GEMS_Receipt_Audit_Service | gems_receipt_audit_pro | 영수증(KR) | Document Receipt 사용 중 |
| **STAY** | 50660 | GEMS_STAY_Invoice_Service | gems_stay_invoice_gen | Basic(템플릿) | 미구현 → 영수증 모델 적용 대상 |

- **TOUR(50152)**: 영수증 특화 모델. Invoke URL 끝이 `/document/receipt` 인 도메인.
- **STAY(50660)**: 현재 Basic(템플릿) 모델. `/infer` 등으로 호출되며 400 이슈 가능 → **STAY에도 영수증 모델을 쓰려면** 아래 설정 사용.

### STAY에 영수증 모델 적용 시 설정 (TOUR 도메인 재사용)

템플릿 적용 전까지 STAY가 TOUR와 **같은 영수증 도메인**을 쓰도록 하려면, **TOUR 서비스(50152)** 의 Invoke URL·Secret을 STAY에도 넣습니다.

| 항목 | STAY 적용 값 (TOUR와 동일) |
|------|----------------------------|
| **사용할 도메인** | TOUR 서비스 **GEMS_Receipt_Audit_Service** (ID 50152) |
| **도메인코드** | `gems_receipt_audit_pro` (참고용, BE env에는 미사용) |
| **Invoke URL** | 50152 도메인에서 **API Gateway 연결** 후 발급한 URL (끝: `/document/receipt`) |
| **Secret Key** | 50152 도메인에서 **API key 발급** 후 발급한 Secret |

**BE 환경 변수 예시 (STAY = TOUR 동일)**  
50152 도메인의 실제 Invoke URL·Secret을 아래처럼 넣습니다.

```env
# 공통: TOUR 도메인(50152) 사용 — STAY/TOUR 모두 이 값 사용
NAVER_OCR_INVOKE_URL=https://8vnzvaz3t6.apigw.ntruss.com/custom/v1/50152/xxxxx/document/receipt
NAVER_OCR_SECRET=50152_도메인에서_발급한_Secret_Key

# STAY 전용 비움 → 위 공통 설정이 STAY에도 적용됨
# NAVER_OCR_STAY_INVOKE_URL=
# NAVER_OCR_STAY_SECRET=
# NAVER_OCR_TOUR_INVOKE_URL=
# NAVER_OCR_TOUR_SECRET=
```

> 실제 URL의 `xxxxx` 부분은 네이버 콘솔에서 50152 → **API Gateway 연결** 후 표시되는 값으로 채우세요.

### STAY 전용 영수증 도메인을 새로 만들 때 (선택)

나중에 STAY만 별도 영수증 도메인을 두고 싶을 때, 콘솔 **도메인 생성** 시 아래처럼 넣을 수 있습니다.

| 항목 | 권장 값 | 비고 |
|------|---------|------|
| **도메인명** | GEMS_STAY_Receipt_Service | 콘솔 표시명 |
| **도메인코드** | gems_stay_receipt_pro | API/연동 식별용, 영문·숫자·하이픈 |
| **인식 모델** | 영수증(KR) | Document Receipt 사용 |
| **용도** | STAY 타입 영수증 (템플릿 적용 전 동일 Receipt API) | |

생성 후 해당 도메인의 Invoke URL·Secret을 `NAVER_OCR_STAY_INVOKE_URL`, `NAVER_OCR_STAY_SECRET` 에만 넣고, TOUR는 기존 50152 유지하면 됩니다.

---

## 3. 현재 구현과의 비교

### 3.1 호출 방식

- **URL**: 도메인별 `NAVER_OCR_*_INVOKE_URL` 또는 단일 `NAVER_OCR_INVOKE_URL` (TOUR/STAY fallback)
- **multipart** 사용 → Base64 대비 전송량·메모리 효율적이며 네이버 권장 방식과 일치.

### 3.2 이미지 전처리 (`_resize_and_compress_for_ocr`)

| 항목 | 현재 값 | 공식 권장 | 비고 |
|------|--------|----------|------|
| 최대 변 길이 | 2000px | **장축 1960px 이하** | 약간 초과 → 1960으로 맞추면 레퍼런스 준수 |
| JPEG 품질 | 80 | 문서 미명시 | **낮을수록 인식률 저하 가능** → 90 권장 |
| 전처리 | EXIF 보정, autocontrast, sharpness 1.2 | - | 선명도 향상 목적이나, 과도하면 노이즈 증폭 가능 |

**인식률 저하 요인 후보**

1. **JPEG 품질 80**: 텍스트 경계가 흐려져 OCR 정확도가 떨어질 수 있음.
2. **과도한 축소**: 원본이 이미 작은데 2000px로만 제한하고 품질 80으로 저장하면 디테일 손실.
3. **저해상도 원본**: 업로드 이미지가 작으면 리사이즈만으로는 개선 한계 → 고해상도 촬영/업스케일 권장.

---

## 4. 응답 구조 (영수증 특화)

- **images[]**: `inferResult`(SUCCESS 등), `receipt.result` 하위에 영수증 필드
- **result** 하위 예: `totalPrice.price.text`, `paymentInfo.date`, `storeInfo.name`, `storeInfo.address` / `addresses[]`, `storeInfo.bizNum`, `paymentInfo.cardInfo.number.text`, `subTotal` 등

현재 파싱 경로(`images[0].receipt.result`) 및 `totalPrice`, `paymentInfo`, `storeInfo`, `subTotal` 보조 추출 로직은 위 구조와 일치.

---

## 4-1. 결제/합계 금액 다중 필드 인식 (인식률 향상)

개별 금액만 인식되고 **합계·결제 금액**이 비어 있으면 합산금액 미달로 이어질 수 있음.  
BE에서는 아래 순서로 **결제/합계 금액**을 추출해 단일 `amount`로 사용한다.

1. **totalPrice.price.text** (기본)
2. **paymentInfo.totalAmount**, **totalAmount**, **paymentAmount**, **supplyPrice**, **amount** 등 result 직하위 키의 `text`/`value`
3. **라벨 기반 수집**: result 전체를 재귀 탐색하며, `name`/`label`이 아래 키워드와 매칭되는 항목의 `text`/`value`를 금액 후보로 수집  
   - **합계금액**, **결제금액**, **공급가액**, **합계**, **거래금액**, **받은금액**, **총액**, **결제액**, **최종결제금액**, **총결제금액**, **합계액**
4. 후보가 여러 개면 **최대값**을 사용 (영수증에서 합계/결제금액이 보통 가장 큼).
5. 위에서도 없으면 **subTotal 부가세**로 총액 추정 (VAT 10% → 세액×10).

이렇게 하면 OCR이 “합계”, “결제금액”, “공급가액” 등 다른 필드명으로만 인식해도 금액이 채워져 합산금액 미달이 줄어든다.

---

## 5. 개선 권장 사항

1. **장축 최대 길이**: 2000 → **1960**으로 변경하여 공식 권장과 동일하게 적용.
2. **JPEG 품질**: 기본값 80 → **90**으로 상향 (인식률 우선 시 95도 검토).
3. **환경 변수로 선택 가능하게** (선택):  
   - `OCR_JPEG_QUALITY` (기본 90), `OCR_MAX_DIMENSION` (기본 1960)  
   - 인식률이 중요하면 품질 95·리사이즈 완화 또는 원본 유지 옵션 검토.
4. **운영 참고**:  
   - 45도 이상 기울어진 영수증은 인식률이 떨어질 수 있음 (가이드 명시).  
   - 저해상도 원본이 많다면, 업스케일(예: Real-ESRGAN) 후 OCR 전송 검토.

---

## 6. 적용한 코드/설정 변경

- **장축 최대**: 2000 → **1960** (환경 변수 `OCR_MAX_DIMENSION`, 기본 1960).
- **JPEG 품질**: 80 → **90** (환경 변수 `OCR_JPEG_QUALITY`, 기본 90).
- `.env.example`에 `OCR_MAX_DIMENSION`, `OCR_JPEG_QUALITY` 주석으로 안내.

인식률이 부족하면 `OCR_JPEG_QUALITY=95` 또는 리사이즈 완화(예: `OCR_MAX_DIMENSION=2400`)로 테스트해 볼 수 있음. 공식 권장은 장축 1960px 이하.

---

## 7. 컨피던스·인식 불량 보정 정책

- **OCR_CONFIDENCE_THRESHOLD** (기본 90): 이 값 이상이면 OCR 결과를 우선 신뢰하고, 미만이면 FE 사용자 입력(금액·결제일·지역)을 참조값으로 사용.
- **OCR_LOW_CONFIDENCE_REVIEW_THRESHOLD** (기본 70): 컨피던스가 이 값 미만이거나 NULL이면 "저신뢰도"로 간주.
- **OCR_KEY_FIELDS_MIN_FILLED** (기본 2): 상점명·사업자번호·주소 3개 중 최소 채워져야 하는 개수.

**OCR_004 (인식 불량·수동 검수 보정)**  
- 조건: (컨피던스 < 70 또는 NULL) **그리고** (핵심 필드 채워진 개수 < 2).  
- 동작: 해당 장을 **PENDING_VERIFICATION**으로 두고, 관리자 페이지에서 상점명·사업자번호·주소 등을 보정할 수 있도록 유도.  
- 인식이 안 된 항목이 많을 때 자동으로 "수동 검수"로 넘기고, 관리자가 보정 후 override로 FIT/UNFIT 처리.

---

## 8. BE에서 인식률 향상 방안 요약

| 구분 | 항목 | 환경 변수 / 설정 | 효과 |
|------|------|------------------|------|
| **이미지 크기** | 장축 상한 | `OCR_MAX_DIMENSION` (기본 1960) | 공식 권장 준수. 너무 낮추면 해상도 손실. |
| **압축 품질** | JPEG 품질 | `OCR_JPEG_QUALITY` (기본 90) | 95로 올리면 텍스트 경계 보존에 유리. |
| **저해상도 업스케일** | 작은 이미지 확대 | `OCR_UPSCALE_SMALL=1`, `OCR_UPSCALE_MAX_SIDE=1200` | 장축이 1200px 미만이면 1960까지 확대 후 전송. 저해상도 업로드 시 인식률 개선. |
| **작은 이미지 PNG** | JPEG 대신 PNG | `OCR_SEND_PNG_WHEN_SMALL=1` | 최종 장축이 1200px 이하일 때 PNG로 전송해 압축 손실 감소. |
| **전처리** | EXIF 보정, autocontrast, sharpness 1.2 | 코드 고정 | 촬영 방향·대비·선명도 보정으로 OCR 안정성 향상. |
| **인식 불량 보정** | 저신뢰도·핵심 필드 누락 | §6 (OCR_004) | 자동 수동 검수 유도로 관리자 보정 가능. |

**권장 순서**  
1. 기본값으로 테스트 후, 저해상도(작은 이미지)가 많으면 `OCR_UPSCALE_SMALL=1` 적용.  
2. 여전히 글자 깨짐/누락이 많으면 `OCR_JPEG_QUALITY=95` 또는 `OCR_SEND_PNG_WHEN_SMALL=1` 시험.  
3. 인식 불량 건은 OCR_004로 수동 검수 후 보정.

**BE 외부**  
- FE: 고해상도 촬영 유도, 흔들림/기울기 최소화.  
- 업스케일: Real-ESRGAN 등 외부 서비스로 전처리 후 전송하는 방식은 BE 범위 외.

---

## 9. STAY OCR 400 Bad Request 대응

- **증상**: STAY 타입 영수증 전송 시 Naver OCR 호출이 `400 Bad Request`로 실패하고, 재시도 후 Fallback OCR(예: easy.gwd)로 결과만 전달되는 경우.
- **원인 후보**: STAY용 Invoke URL이 **Document OCR Receipt**(`/document/receipt`)가 아닌 **Custom/General OCR**(`/infer`)인 경우, 요청 형식·필수 필드가 다를 수 있음. 또는 이미지 형식·크기 제한, 템플릿 ID 필수 등.
- **조치**:
  1. **로그 확인**: 400 발생 시 BE 로그에 `Naver OCR ... (domain=STAY): status=400 body=...` 형태로 **응답 본문**이 출력됨. 해당 body에서 Naver가 반환한 에러 메시지 확인.
  2. **URL/Secret**: `NAVER_OCR_STAY_INVOKE_URL`이 Document OCR Receipt 엔드포인트(`.../document/receipt`)인지, Custom/General(`.../infer`)인지 확인. Document Receipt와 동일한 multipart 형식을 쓰려면 Receipt URL 사용 권장.
  3. **Custom Infer 사용 시**: Naver 콘솔에서 해당 Custom API의 요청 스펙(필수 필드, templateIds 등) 확인 후, 필요 시 BE에서 STAY 전용 요청 형식 분기 구현.

---

## 10. 참고 링크

- [CLOVA OCR 예제 (Text OCR 호출)](https://guide.ncloud-docs.com/docs/clovaocr-example01)
- [Document OCR - Receipt](https://api.ncloud-docs.com/docs/ai-application-service-ocr-ocrdocumentocr-receipt)
- [CLOVA OCR 사용 준비 / 스펙](https://guide-fin.ncloud-docs.com/docs/clovaocr-spec) — 호출 성능 권장 1 tps 등

- **프로젝트**: `PROJECT/네이버_CLOVA_OCR_레퍼런스_및_인식률_검토.md` (본 문서), `.env.example` (OCR_* 환경 변수)
