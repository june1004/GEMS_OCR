# MinIO–DB 정합성 및 OCR 미인식 이미지 정책

## 1. 상황 정리

- **MinIO**: Presigned URL로 업로드된 이미지가 `receipts/{submission_id}_{8자리hex}_{파일명}` 형식으로 저장됨.
- **DB**: Presigned 호출 시 `submissions` 행 생성, Complete 호출 후 `receipt_items` 생성 및 OCR·판정 반영.

**발생할 수 있는 불일치**

1. MinIO에는 객체가 있는데 DB에 해당 `submission_id`가 없음 (드묾, Presigned 응답 후 commit 실패 등).
2. DB에는 `submissions`만 있고 **Complete가 호출되지 않음** → `receipt_items` 없음, status는 PENDING.
3. Complete는 했는데 **OCR 미인식(ERROR_OCR)** → `receipt_items`에 저장되나 이미지 활용/검수 대상으로 별도 검증 필요.

---

## 2. MinIO에만 있거나 Complete 안 된 건 — 유효기간·처리

### 2.1 “유효” 정의

| 구분 | 설명 | 유효 여부 |
|------|------|-----------|
| Presigned만 하고 업로드 안 함 | MinIO에 객체 없음 | - |
| 업로드만 하고 Complete 안 함 | MinIO에 객체 있음, DB에 submission 있음, receipt_items 없음 | **미완료** |
| Complete 호출됨 | receipt_items 존재, status FIT/UNFIT/ERROR 등 | **완료** |

- **업로드만 하고 Complete를 호출하지 않은 건**: “제출 완료”가 아니므로 **미완료 신청**으로 간주.
- **유효 기간**: 업로드 시점 기준 **관리자 설정(기본 각 1일)** 동안만 “대기 중”으로 두고, 그 이후에는 **정합성 정리 대상**으로 본다.

### 2.2 처리 방안

1. **정기 점검(리콘실리레이션)**  
   - MinIO `receipts/` 목록을 읽어, 각 객체 키에서 `submission_id` 추출.  
   - DB에서 해당 ID의 존재 여부, `receipt_items` 존재 여부, `submissions.status` 조회.  
   - **보고서**: (A) DB에 없는 submission_id, (B) submission은 있으나 receipt_items 없음(PENDING), (C) 완료된 건.

2. **유효기간 경과 후 정리**  
   - **객체 키 형식**이 `receipts/{submission_id}_...` 이고,  
     - DB에 해당 `submission_id`가 없거나,  
     - 있더라도 `created_at`(또는 객체 LastModified)이 **N일 이전**이고 **receipt_items가 없음**  
     → “고아/미완료 객체”로 간주.  
   - 정책에 따라:  
     - **보관**: 일정 기간 더 보관 후 재점검.  
     - **삭제**: MinIO 객체만 삭제(DB에 없는 경우), 또는 submission이 있으면 status를 EXPIRED 등으로 변경 후 객체 삭제.  
   - **실행**: 스크립트로 목록 출력·검토 후, 삭제는 별도 플래그(`--dry-run` 기본, `--delete` 시에만 삭제)로 수행 권장.

3. **관리자 설정**  
   - **GET/PUT** `/api/v1/admin/rules/judgment` 에서 `orphan_object_days`, `expired_candidate_days` 조회·수정. 기본값 각 **1일**, 범위 1~365일.  

---

## 3. OCR 미인식 이미지 검증 방안

### 3.1 대상

- `receipt_items.status = 'ERROR_OCR'` 또는 `error_code = 'OCR_001'`.
- 또는 OCR 결과가 비어 있어 실제 판정에 사용되지 않은 장.

### 3.2 검증 항목

1. **건수·비율**  
   - 기간별로 ERROR_OCR 건수, 해당 submission 수, 전체 대비 비율.  
   - 비율이 높으면 업로드 품질(해상도, 포맷) 또는 OCR 설정 점검.

2. **이미지 유효성**  
   - MinIO 객체가 실제 이미지 바이너리인지(시그니처 검사), 크기·Content-Type.  
   - `check_s3_image_object.py`로 샘플 검사 가능.

3. **재처리 여부**  
   - 동일 `image_key`로 OCR 재시도(수동 트리거 또는 배치) 가능 여부.  
   - 재시도 시 네이버 OCR 한도·비용 고려.

### 3.3 운영 절차 제안

- **주기 점검**: 주 1회(또는 월 1회) ERROR_OCR 건수/비율 조회.  
- **샘플 검증**: ERROR_OCR 중 일부에 대해 MinIO 객체 진단 스크립트 실행.  
- **대응**:  
  - 이미지 손상/비정상 → FE 업로드 방식·Presigned PUT 본문 검토.  
  - 정상 이미지인데 OCR만 실패 → 재시도 또는 관리자 수동 판정 플로우 검토.

---

## 4. 스크립트·쿼리 위치

- **MinIO–DB 정합**: `PROJECT/scripts/reconcile_minio_db.py` (아래에서 정의).  
- **OCR 미인식 집계**: `PROJECT/scripts/status_원인_분석.sql` 및 `analyze_status_causes.py`에서 error_code/ERROR_OCR 집계 가능.  
- **이미지 객체 진단**: `PROJECT/scripts/check_s3_image_object.py`.

---

## 5. 요약

| 구분 | 유효기간(기본) | 설정 | 처리 |
|------|----------------|------|------|
| MinIO에만 있는 객체(고아) | 1일 | 관리자 `orphan_object_days` (1~365) | 리콘실리레이션 보고, `--delete` 시 유효기간 경과분만 삭제 |
| DB에 submission만 있고 Complete 없음(만료 후보) | 1일 | 관리자 `expired_candidate_days` (1~365) | 보고·만료 후보 건수 표시 |
| OCR 미인식(ERROR_OCR) | - | - | 주기 집계·샘플 이미지 검증·재시도/수동 판정 검토 |
