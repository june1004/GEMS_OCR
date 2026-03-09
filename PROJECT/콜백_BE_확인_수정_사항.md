# OCR 결과 콜백 – BE 확인·수정 사항

## BE에서 확인할 사항

1. **환경 변수**
   - `OCR_RESULT_CALLBACK_URL`: 콜백 수신 URL이 올바른지 (운영: https://easy.gwd.go.kr/dg/coupon/api/ocr/result 등)
   - `OCR_CALLBACK_TIMEOUT_SEC`: 수신 서버가 느리면 20~30 초로 설정 (기본 15)
   - `OCR_CALLBACK_RETRIES`: 연결/타임아웃 시 재시도 횟수 (기본 2 → 최대 3회 시도)

2. **네트워크**
   - BE 서버에서 수신 URL(easy.gwd.go.kr)로 **아웃바운드 HTTP/HTTPS** 가능한지 (방화벽/프록시)
   - 수신 측 서버가 해당 경로에서 정상 응답하는지

3. **로그·감사**
   - 실패 시 `OCR result callback failed` (4xx/5xx 응답) 또는 `OCR result callback error (no retry)` (연결/예외)
   - AdminAuditLog `CALLBACK_SEND` 로그로 receiptId·status·response_body·attempt 확인

---

## 적용한 수정 사항

| 항목 | 내용 |
|------|------|
| **타임아웃** | `OCR_CALLBACK_TIMEOUT_SEC` 환경변수로 설정 가능. 기본 15초, 5~60초로 제한. |
| **재시도** | `OCR_CALLBACK_RETRIES`(기본 2)만큼 **연결/타임아웃** 시에만 재시도. 4xx 응답은 재시도 안 함. |
| **에러 로그** | 예외 시 `err=` 비는 경우 방지. `type(e).__name__` 또는 메시지 출력. |
| **감사 로그** | 실패 시에도 `error`, `attempt` 메타 저장. |

수신 측에서 400 "receiptId mismatching" 등이 나오면 **수신 API 스펙**에 맞게 payload를 맞추거나, 수신 측에서 BE가 보내는 `receiptId`/`receipt_id`, `userUuid`/`user_uuid`를 사용하도록 수정해야 합니다.
