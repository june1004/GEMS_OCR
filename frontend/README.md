# GEMS OCR 프론트엔드 (영수증 업로드)

동적 엔트리 기반 영수증 등록 UI. 1:1, 1:최대3, 이미지 단독 전송 등 데이터 모델 변경에 대응할 수 있도록 배열 상태로 설계되어 있습니다.

## 실행

```bash
cd frontend
npm install
npm run dev
```

브라우저: http://localhost:5173

## 환경 변수

- `VITE_API_BASE_URL`: API 서버 주소 (기본 `http://localhost:8000`)
- `.env.example`을 복사해 `.env` 생성 후 설정

## 구조

- **상태**: `receiptEntries` — 영수증 한 장당 하나의 엔트리(id, image, objectKey, receiptId, metadata, status)
- **ReceiptCard**: 이미지 미리보기 + 타입별 폼(숙박=소재지, 관광=상호명, 공통=결제일·금액·카드 앞 4자리) + 삭제
- **업로드**: 이미지 선택 시 즉시 Presigned URL 발급 → 스토리지 PUT (제출 전 업로드 완료)
- **제출**: 엔트리별로 `POST /api/v1/receipts/complete` 호출 후 결과 Polling

## BE API

- `POST /api/v1/receipts/presigned-url` (fileName, contentType, userUuid, type)
- `PUT {uploadUrl}` (이미지 바디)
- `POST /api/v1/receipts/complete` (receiptId, userUuid, type, campaignId, data)
- `GET /api/v1/receipts/status/{receiptId}`
