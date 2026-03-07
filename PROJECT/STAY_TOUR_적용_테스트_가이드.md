# STAY/TOUR 분기 적용 — 테스트 가이드

> Presigned 경로 분기·OCR 도메인 분기가 정상 동작하는지 확인하는 방법입니다. **FE 변경 없이** BE만으로 검증할 수 있습니다.

---

## 1. 사전 확인 (환경)

### 1.1 헬스 체크

```bash
curl -s https://api.nanum.online/api/health
# 또는 로컬: curl -s http://localhost:8000/api/health
```

- `status: "ok"`, `s3: "ok"`, `db: "ok"` 이면 기본 동작 가능.

### 1.2 환경 변수 (Coolify/운영)

- **STAY/TOUR 분기 사용 시**:  
  `NAVER_OCR_STAY_INVOKE_URL`, `NAVER_OCR_STAY_SECRET`, `NAVER_OCR_TOUR_INVOKE_URL`, `NAVER_OCR_TOUR_SECRET` 설정 후 **Redeploy**.
- **미설정**: 기존 `NAVER_OCR_INVOKE_URL`, `NAVER_OCR_SECRET` 가 STAY·TOUR 모두에 사용됨 (동작은 하나, 분기만 경로로 적용).

### 1.3 MinIO

- 버킷에 `STAY/`, `TOUR/` prefix로 객체가 쌓일 수 있으면 됨 (폴더는 자동 생성).

---

## 2. 체크리스트 — 무엇을 검증하는가

| # | 검증 항목 | 확인 방법 |
|---|-----------|-----------|
| 1 | Presigned 시 **objectKey에 STAY/ 또는 TOUR/ prefix** | 2.1 |
| 2 | **STAY** 한 건: Presigned(type=STAY) → 업로드 → Complete(type=STAY) → Status 정상 | 2.2 |
| 3 | **TOUR** 한 건: Presigned(type=TOUR) → 업로드 → Complete(type=TOUR) → Status 정상 | 2.2 |
| 4 | MinIO에 **STAY/receipts/**, **TOUR/receipts/** 아래에 파일 생성 여부 | 2.3 |
| 5 | (선택) 기존 경로(receipts/...) 이미지로 Complete 시 **TOUR로 OCR** 동작 | 2.4 |

---

## 3. 테스트 방법

### 3.1 Presigned URL — 경로 분기 확인

**STAY**

```bash
curl -s -X POST "https://api.nanum.online/api/v1/receipts/presigned-url?fileName=test.jpg&contentType=image/jpeg&userUuid=test-user&type=STAY" | jq .
```

- **확인**: 응답의 `objectKey` 가 **`STAY/receipts/`** 로 시작하는지.

**TOUR**

```bash
curl -s -X POST "https://api.nanum.online/api/v1/receipts/presigned-url?fileName=test.jpg&contentType=image/jpeg&userUuid=test-user&type=TOUR" | jq .
```

- **확인**: 응답의 `objectKey` 가 **`TOUR/receipts/`** 로 시작하는지.

- `receiptId`, `objectKey`, `uploadUrl` 을 저장해 두고 3.2에서 사용.

---

### 3.2 한 건씩 E2E (STAY 1건, TOUR 1건)

1. **Presigned**  
   - `type=STAY` 또는 `type=TOUR` 로 요청 → `receiptId`, `objectKey`, `uploadUrl` 저장.
2. **업로드**  
   - `uploadUrl` 로 이미지 파일 **PUT** (동일한 receiptId로 추가 장 올릴 때만 Presigned 다시 호출).
3. **Complete**  
   - `receiptId`, `userUuid`, `type`(Presigned과 동일: STAY 또는 TOUR), `documents: [{ imageKey: objectKey }]` 전송.
4. **Status**  
   - `GET /api/v1/receipts/{receiptId}/status` 로 폴링 → `overall_status` 가 `FIT` / `UNFIT` / `VERIFYING` 등으로 오면 OCR까지 정상 동작한 것.

**예시 (TOUR 한 장, bash + jq)**

```bash
BASE="https://api.nanum.online"
UUID="test-user-$(date +%s)"

# 1) Presigned (TOUR)
RES=$(curl -s -X POST "$BASE/api/v1/receipts/presigned-url?fileName=receipt.jpg&contentType=image/jpeg&userUuid=$UUID&type=TOUR")
echo "$RES" | jq .
RECEIPT_ID=$(echo "$RES" | jq -r .receiptId)
OBJECT_KEY=$(echo "$RES" | jq -r .objectKey)
UPLOAD_URL=$(echo "$RES" | jq -r .uploadUrl)

# objectKey 가 TOUR/receipts/ 로 시작하는지 확인
echo "$OBJECT_KEY" | grep -q "^TOUR/receipts/" && echo "OK: TOUR path" || echo "FAIL: path prefix"

# 2) 업로드 (실제 이미지 파일 경로로 교체)
# curl -s -X PUT -H "Content-Type: image/jpeg" --data-binary @/path/to/receipt.jpg "$UPLOAD_URL"

# 3) Complete (2단계 후 실행)
# curl -s -X POST "$BASE/api/v1/receipts/complete" -H "Content-Type: application/json" -d "{\"receiptId\":\"$RECEIPT_ID\",\"userUuid\":\"$UUID\",\"type\":\"TOUR\",\"data\":{\"documents\":[{\"imageKey\":\"$OBJECT_KEY\",\"docType\":\"RECEIPT\"}]}}"

# 4) Status
# curl -s "$BASE/api/v1/receipts/$RECEIPT_ID/status" | jq .
```

- STAY 도 동일하게 `type=STAY` 로 1~4단계 수행 후, Presigned 응답의 `objectKey` 가 `STAY/receipts/` 로 시작하는지와 Status 응답을 확인.

---

### 3.3 MinIO에서 저장 위치 확인

- MinIO 콘솔(또는 mc CLI)에서 버킷 내부 확인.
- **STAY** 로 한 건 올린 뒤: `STAY/receipts/{receiptId}_{uuid}_{fileName}` 형태 객체 존재.
- **TOUR** 로 한 건 올린 뒤: `TOUR/receipts/{receiptId}_{uuid}_{fileName}` 형태 객체 존재.

---

### 3.4 기존 경로(receipts/...) 호환

- 예전에 **prefix 없이** `receipts/xxx_yyy.jpg` 로 저장된 이미지로 Complete 호출하는 경우:
  - **도메인**: `project_type`(Complete의 `type`) 또는 기본 **TOUR** 로 OCR 호출됨.
- 해당 receiptId로 Status 조회 시 에러 없이 결과가 오면 호환 동작 OK.

---

## 4. 문제 발생 시 확인할 것

| 현상 | 확인할 점 |
|------|-----------|
| Presigned objectKey가 `receipts/...` 만 나옴 (STAY/TOUR prefix 없음) | **배포 서버(Coolify 등)에 최신 코드가 반영되었는지 확인.** 최신 BE에서는 `objectKey`가 반드시 `STAY/receipts/...` 또는 `TOUR/receipts/...` 로 시작함. 응답에 `storagePrefix`(STAY 또는 TOUR)가 있으면 분기 로직 적용된 버전. |
| Presigned objectKey에 STAY/TOUR 없음 | 1) 서버 **Redeploy**(git pull 또는 이미지 재빌드 후 재기동). 2) 요청 쿼리에 `type=STAY` 또는 `type=TOUR` 포함 여부. (미포함 시 기본 TOUR로 저장됨) |
| OCR 실패(ERROR_OCR 등) | 해당 도메인(STAY/TOUR)의 Invoke URL·Secret이 Coolify에 올바르게 설정되었는지, Redeploy 했는지. |
| MinIO 403/404 | Presigned URL 만료(10분), 버킷 정책, S3 엔드포인트/키. |
| Status 500 | BE 로그에서 stack trace 확인. |

---

## 5. 요약

1. **Presigned** 두 번 호출(type=STAY, type=TOUR) → `objectKey` prefix만 확인해도 경로 분기는 검증됨.
2. **STAY 1건, TOUR 1건** 각각 Presigned → 업로드 → Complete → Status 까지 진행해 보면 OCR 분기·전체 플로우 검증.
3. MinIO에 `STAY/receipts/`, `TOUR/receipts/` 아래에 파일이 생기면 저장 경로 분기 정상.

*문서 버전: 1.0 | GEMS OCR BE STAY/TOUR 분기 기준*
