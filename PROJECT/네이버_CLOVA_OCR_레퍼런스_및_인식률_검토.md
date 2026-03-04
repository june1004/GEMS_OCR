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

## 2. 현재 구현과의 비교

### 2.1 호출 방식

- **URL**: `NAVER_OCR_INVOKE_URL` 환경 변수 (예: `https://xxx.apigw.ntruss.com/custom/v1/{domain}/{key}/document/receipt`)
- **multipart** 사용 → Base64 대비 전송량·메모리 효율적이며 네이버 권장 방식과 일치.

### 2.2 이미지 전처리 (`_resize_and_compress_for_ocr`)

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

## 3. 응답 구조 (영수증 특화)

- **images[]**: `inferResult`(SUCCESS 등), `receipt.result` 하위에 영수증 필드
- **result** 하위 예: `totalPrice.price.text`, `paymentInfo.date`, `storeInfo.name`, `storeInfo.address` / `addresses[]`, `storeInfo.bizNum`, `paymentInfo.cardInfo.number.text`, `subTotal` 등

현재 파싱 경로(`images[0].receipt.result`) 및 `totalPrice`, `paymentInfo`, `storeInfo`, `subTotal` 보조 추출 로직은 위 구조와 일치.

---

## 4. 개선 권장 사항

1. **장축 최대 길이**: 2000 → **1960**으로 변경하여 공식 권장과 동일하게 적용.
2. **JPEG 품질**: 기본값 80 → **90**으로 상향 (인식률 우선 시 95도 검토).
3. **환경 변수로 선택 가능하게** (선택):  
   - `OCR_JPEG_QUALITY` (기본 90), `OCR_MAX_DIMENSION` (기본 1960)  
   - 인식률이 중요하면 품질 95·리사이즈 완화 또는 원본 유지 옵션 검토.
4. **운영 참고**:  
   - 45도 이상 기울어진 영수증은 인식률이 떨어질 수 있음 (가이드 명시).  
   - 저해상도 원본이 많다면, 업스케일(예: Real-ESRGAN) 후 OCR 전송 검토.

---

## 5. 적용한 코드/설정 변경

- **장축 최대**: 2000 → **1960** (환경 변수 `OCR_MAX_DIMENSION`, 기본 1960).
- **JPEG 품질**: 80 → **90** (환경 변수 `OCR_JPEG_QUALITY`, 기본 90).
- `.env.example`에 `OCR_MAX_DIMENSION`, `OCR_JPEG_QUALITY` 주석으로 안내.

인식률이 부족하면 `OCR_JPEG_QUALITY=95` 또는 리사이즈 완화(예: `OCR_MAX_DIMENSION=2400`)로 테스트해 볼 수 있음. 공식 권장은 장축 1960px 이하.

---

## 6. 컨피던스·인식 불량 보정 정책

- **OCR_CONFIDENCE_THRESHOLD** (기본 90): 이 값 이상이면 OCR 결과를 우선 신뢰하고, 미만이면 FE 사용자 입력(금액·결제일·지역)을 참조값으로 사용.
- **OCR_LOW_CONFIDENCE_REVIEW_THRESHOLD** (기본 70): 컨피던스가 이 값 미만이거나 NULL이면 "저신뢰도"로 간주.
- **OCR_KEY_FIELDS_MIN_FILLED** (기본 2): 상점명·사업자번호·주소 3개 중 최소 채워져야 하는 개수.

**OCR_004 (인식 불량·수동 검수 보정)**  
- 조건: (컨피던스 < 70 또는 NULL) **그리고** (핵심 필드 채워진 개수 < 2).  
- 동작: 해당 장을 **PENDING_VERIFICATION**으로 두고, 관리자 페이지에서 상점명·사업자번호·주소 등을 보정할 수 있도록 유도.  
- 인식이 안 된 항목이 많을 때 자동으로 "수동 검수"로 넘기고, 관리자가 보정 후 override로 FIT/UNFIT 처리.

---

## 7. BE에서 인식률 향상 방안 요약

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

## 8. 참고 링크

- [CLOVA OCR 예제 (Text OCR 호출)](https://guide.ncloud-docs.com/docs/clovaocr-example01)
- [Document OCR - Receipt](https://api.ncloud-docs.com/docs/ai-application-service-ocr-ocrdocumentocr-receipt)
- [CLOVA OCR 사용 준비 / 스펙](https://guide-fin.ncloud-docs.com/docs/clovaocr-spec) — 호출 성능 권장 1 tps 등

- **프로젝트**: `PROJECT/네이버_CLOVA_OCR_레퍼런스_및_인식률_검토.md` (본 문서), `.env.example` (OCR_* 환경 변수)
