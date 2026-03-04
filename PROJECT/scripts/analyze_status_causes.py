#!/usr/bin/env python3
"""
신청(submission) status별 건수·원인 분석.
FIT 적고 UNFIT/ERROR/PENDING 많을 때 원인 파악용.
사용: DATABASE_URL 설정 후 `python PROJECT/scripts/analyze_status_causes.py`
"""
import os
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL 환경 변수가 없습니다.")
    sys.exit(1)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[11:]
elif DATABASE_URL.startswith("postgresql://") and "+psycopg2" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

from sqlalchemy import create_engine, text


def main():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        print("=" * 60)
        print("1. 신청(submissions) status 별 건수")
        print("=" * 60)
        r = conn.execute(text("""
            SELECT status, COUNT(*) AS cnt
            FROM submissions
            GROUP BY status
            ORDER BY cnt DESC
        """))
        rows = r.fetchall()
        total = sum(row[1] for row in rows)
        for status, cnt in rows:
            pct = (cnt / total * 100) if total else 0
            print(f"  {status or '(NULL)':30} {cnt:6}건  ({pct:5.1f}%)")
        print(f"  {'총계':30} {total:6}건")

        print()
        print("=" * 60)
        print("2. 신청 status 별 · project_type 별 건수")
        print("=" * 60)
        r = conn.execute(text("""
            SELECT status, project_type, COUNT(*) AS cnt
            FROM submissions
            GROUP BY status, project_type
            ORDER BY status, project_type
        """))
        for status, ptype, cnt in r.fetchall():
            print(f"  {status or '(NULL)':25} {ptype or '(NULL)':8} {cnt:6}건")

        print()
        print("=" * 60)
        print("3. UNFIT/ERROR/PENDING* 신청의 fail_reason(원인) 별 건수")
        print("=" * 60)
        r = conn.execute(text("""
            SELECT COALESCE(global_fail_reason, fail_reason, '(비어있음)') AS reason, COUNT(*) AS cnt
            FROM submissions
            WHERE status IN ('UNFIT', 'ERROR', 'PENDING', 'PENDING_NEW', 'PENDING_VERIFICATION', 'PROCESSING', 'VERIFYING')
            GROUP BY COALESCE(global_fail_reason, fail_reason, '(비어있음)')
            ORDER BY cnt DESC
        """))
        for reason, cnt in r.fetchall():
            reason_show = (reason or "(NULL)")[:55]
            print(f"  {reason_show:55} {cnt:6}건")

        print()
        print("=" * 60)
        print("4. 장(receipt_items) error_code 별 건수 (해당 장이 속한 신청이 비적격/오류/대기인 경우)")
        print("=" * 60)
        r = conn.execute(text("""
            SELECT ri.error_code, COUNT(*) AS cnt
            FROM receipt_items ri
            JOIN submissions s ON s.submission_id = ri.submission_id
            WHERE s.status IN ('UNFIT', 'ERROR', 'PENDING', 'PENDING_NEW', 'PENDING_VERIFICATION')
            GROUP BY ri.error_code
            ORDER BY cnt DESC
        """))
        for code, cnt in r.fetchall():
            print(f"  {code or '(NULL)':35} {cnt:6}건")

        print()
        print("=" * 60)
        print("5. 장(receipt_items) status 별 건수")
        print("=" * 60)
        r = conn.execute(text("""
            SELECT status, COUNT(*) AS cnt
            FROM receipt_items
            GROUP BY status
            ORDER BY cnt DESC
        """))
        for status, cnt in r.fetchall():
            print(f"  {status or '(NULL)':35} {cnt:6}건")

        print()
        print("=" * 60)
        print("6. 최근 비적격/오류/대기 신청 샘플 (원인 확인용)")
        print("=" * 60)
        r = conn.execute(text("""
            SELECT submission_id, status, project_type,
                   COALESCE(global_fail_reason, fail_reason) AS reason,
                   created_at
            FROM submissions
            WHERE status IN ('UNFIT', 'ERROR', 'PENDING_NEW', 'PENDING_VERIFICATION')
            ORDER BY created_at DESC
            LIMIT 20
        """))
        for sid, status, ptype, reason, created in r.fetchall():
            reason_show = (reason or "")[:40] if reason else ""
            print(f"  {sid[:36]}  {status:22} {ptype or '':6}  {reason_show:40}  {str(created)[:19]}")

    print()
    print("분석 완료. 3·4번에서 상위 원인/에러코드를 확인해 조치하세요.")


if __name__ == "__main__":
    main()
