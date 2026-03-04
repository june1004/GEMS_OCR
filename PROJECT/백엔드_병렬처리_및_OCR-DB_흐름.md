# 백엔드 병렬 처리 및 OCR → DB 흐름

## 1. OCR 인식 후 DB 저장 흐름 (검증 요약)

- **MinIO(S3)**  
  FE가 presigned URL로 업로드한 이미지가 저장됨.

- **Complete 요청**  
  FE가 `POST /api/v1/receipts/complete`로 `documents`(imageKey 등) 전달.

- **백그라운드 태스크 (`analyze_receipt_task`)**  
  1. 해당 receiptId의 submission·documents 기준으로 **receipt_items** placeholder 생성 후 `status = VERIFYING`으로 한 번 **commit**.  
  2. **MinIO에서 이미지 바이너리** 조회 → **네이버 OCR API** 호출(재시도 포함) → 응답 검증(`_validate_naver_ocr_response`).  
  3. OCR 결과를 **map_ocr_to_db**로 `ReceiptItem` 형태로 매핑(메모리만 사용, DB 미사용).  
  4. 기존 **receipt_items**를 위 결과로 **in-place 업데이트** 후, 유형별(STAY/TOUR) 검증·판정.  
  5. **finalize_submission**으로 submission 상태·금액·사유 설정 후 한 번에 **commit**.  
  6. **콜백** (`_send_result_callback`) 전송.

- **정리**  
  OCR → 파싱 → 매핑 → 검증 → submission/receipt_items 갱신 → 1회 commit → 콜백.  
  예외 시에는 `analyze_receipt_task`의 except에서 submission을 ERROR로 두고 commit 후 콜백 호출.

---

## 2. 병렬 처리 구조 (동시 제출·인식·분석 시 충돌 방지)

### 2.1 서로 다른 receiptId (다건 동시 제출)

- **태스크별 독립 세션**  
  `analyze_receipt_task`는 호출마다 **새로운 `SessionLocal()`**를 사용.  
  → 서로 다른 receiptId에 대한 태스크는 **서로 다른 DB 세션**을 쓰므로 **충돌 없음**.

- **공유 상태 없음**  
  각 태스크는 자신의 `req.receiptId`만 사용.  
  전역 변수·캐시 등 공유 상태 없음.

### 2.2 동일 receiptId (중복 Complete 방지)

- **원자적 전환**  
  `_submit_receipt_common`에서  
  `UPDATE submissions SET status = 'PROCESSING', ... WHERE submission_id = :id AND status = 'PENDING'`  
  로 **한 번에 한 요청만** PENDING → PROCESSING 전환.

- **동시 요청 시**  
  첫 요청만 `rowcount > 0`으로 성공하고 백그라운드 태스크 1개만 등록.  
  나머지 요청은 `rowcount == 0` → DB에서 현재 상태를 다시 읽어  
  `PROCESSING` 또는 `VERIFYING`를 그대로 반환.

- **결과**  
  동일 receiptId에 대해 **analyze_receipt_task는 항상 1개만** 실행됨.

### 2.3 요약

| 구분 | 내용 |
|------|------|
| 다른 receiptId 여러 건 동시 제출 | 태스크별 별도 세션 → 병렬 처리, DB 충돌 없음. |
| 같은 receiptId에 Complete 동시 다중 요청 | 원자적 PENDING→PROCESSING 업데이트로 한 건만 처리, 나머지는 현재 상태 반환. |
| OCR → DB | 1 receiptId = 1 세션, VERIFYING commit → OCR → 최종 판정 commit → 콜백. |

---

## 3. 코드 위치 참고

- 원자적 전환: `main.py` `_submit_receipt_common` 내 `update(Submission).where(..., status == "PENDING").values(...)`  
- 태스크별 세션: `main.py` `analyze_receipt_task` 시작 시 `db = SessionLocal()`  
- OCR 응답 검증: `main.py` `_validate_naver_ocr_response`, `_call_naver_ocr_binary`  
- OCR → DB 매핑: `main.py` `map_ocr_to_db`, 그 다음 `analyze_receipt_task` 내 receipt_items 갱신 및 `finalize_submission` 후 `db.commit()`
