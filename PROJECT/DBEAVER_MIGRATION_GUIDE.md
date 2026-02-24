# DBeaver에서 receipts 마이그레이션 적용하기

## 1. DB 연결 (이미 연결돼 있으면 2번으로)

1. DBeaver 실행 → **데이터베이스** → **새 데이터베이스 연결** (또는 `Ctrl+Shift+N`)
2. **PostgreSQL** 선택 → **다음**
3. 연결 정보 입력:
   - **호스트**: `72.61.126.181` (또는 실제 호스트)
   - **포트**: `5432`
   - **데이터베이스**: `gems`
   - **사용자명**: `postgres`
   - **비밀번호**: (실제 비밀번호 입력)
4. **테스트 연결** → 성공하면 **완료**

---

## 2. gems 데이터베이스로 이동

- 왼쪽 **데이터베이스 네비게이터**에서  
  `PostgreSQL` → 해당 연결 → **gems** 데이터베이스를 더블클릭해 연결  
  (또는 `gems` 우클릭 → **SQL 편집기** → **SQL 스크립트**)

---

## 3. SQL 스크립트 열기

**방법 A – 파일로 열기**

1. 상단 메뉴 **SQL 편집기** → **SQL 스크립트 열기** (또는 `Ctrl+Shift+O`)
2. 프로젝트 안 아래 파일 선택:
   ```
   PROJECT/migrations/receipts_fe_columns.sql
   ```
3. 열리면 스크립트가 편집기에 표시됨

**방법 B – 직접 붙여넣기**

1. **gems** 연결에서 **SQL 편집기** → **새 SQL 스크립트** (또는 `Ctrl+]`)
2. 아래 SQL 전체를 복사해 붙여넣기:

```sql
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS image_key VARCHAR(500);
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS image_keys TEXT[];
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS documents JSONB;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS business_num VARCHAR(50);
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS ocr_assets JSONB;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS audit_trail TEXT;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS submission_type VARCHAR(50);
```

---

## 4. 실행하기

- **전체 스크립트 실행**: 편집기에서 **Ctrl+A**(전체 선택) → **Ctrl+Enter** (또는 상단 **실행** 버튼 ▶)  
  → 반드시 **전체를 선택한 뒤** 실행하세요. 한 줄만 실행하면 나머지 컬럼이 추가되지 않습니다.
- **파일 사용 시**: `PROJECT/migrations/receipts_fe_columns_run_in_dbeaver.sql` 을 열고 같은 방식으로 **Ctrl+A** → **Ctrl+Enter**
- 한 문장만 실행하면 (커서 놓고 Ctrl+Enter) 그 한 줄만 적용되고, **image_key, image_keys, documents** 등이 빠질 수 있습니다.

---

## 5. 적용 여부 확인

같은 SQL 편집기에서 아래 쿼리만 선택한 뒤 **실행** (`Ctrl+Enter`):

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'receipts'
ORDER BY ordinal_position;
```

결과에 **image_key**, **image_keys**, **documents** 가 있으면 정상 반영된 것입니다.

---

## 요약

| 단계 | 동작 |
|------|------|
| 1 | PostgreSQL로 `gems` DB 연결 |
| 2 | SQL 편집기에서 `receipts_fe_columns.sql` 열기 또는 위 ALTER 문 붙여넣기 |
| 3 | `Ctrl+Enter`로 전체 실행 |
| 4 | 확인 쿼리로 `receipts` 컬럼 목록 조회 |
