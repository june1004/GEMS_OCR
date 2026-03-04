#!/usr/bin/env python3
"""
분석 중 멈춘 신청(PROCESSING/VERIFYING)을 ERROR로 복구.
사용: python PROJECT/scripts/mark_stuck_submissions_error.py [submission_id]
     또는 python PROJECT/scripts/mark_stuck_submissions_error.py --all --minutes 15
"""
import os
import sys
from pathlib import Path

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
    args = sys.argv[1:]
    engine = create_engine(DATABASE_URL)

    if "--all" in args:
        try:
            i = args.index("--minutes")
            minutes = int(args[i + 1])
        except (ValueError, IndexError):
            minutes = 15
        with engine.begin() as conn:
            r = conn.execute(
                text("""
                    UPDATE submissions
                    SET status = 'ERROR',
                        global_fail_reason = '분석 지연(자동 복구)',
                        fail_reason = '분석 지연(자동 복구)',
                        audit_trail = COALESCE(audit_trail, '') || ' | [복구] 자동 ERROR 처리',
                        audit_log = COALESCE(audit_log, '') || ' | [복구] 자동 ERROR 처리'
                    WHERE status IN ('PROCESSING', 'VERIFYING')
                      AND created_at < NOW() - (:minutes || ' minutes')::interval
                    RETURNING submission_id
                """),
                {"minutes": minutes},
            )
            ids = [row[0] for row in r.fetchall()]
        print(f"✅ {len(ids)}건을 ERROR로 복구했습니다: {ids[:10]}{'...' if len(ids) > 10 else ''}")
        return

    if not args:
        print("사용법: python mark_stuck_submissions_error.py <submission_id>")
        print("     또는: python mark_stuck_submissions_error.py --all [--minutes 15]")
        sys.exit(1)

    submission_id = args[0].strip()
    with engine.begin() as conn:
        r = conn.execute(
            text("""
                UPDATE submissions
                SET status = 'ERROR',
                    global_fail_reason = '분석 지연(수동 조치)',
                    fail_reason = '분석 지연(수동 조치)',
                    audit_trail = COALESCE(audit_trail, '') || ' | [복구] 수동 ERROR 처리',
                    audit_log = COALESCE(audit_log, '') || ' | [복구] 수동 ERROR 처리'
                WHERE submission_id = :sid
                  AND status IN ('PROCESSING', 'VERIFYING')
                RETURNING submission_id
            """),
            {"sid": submission_id},
        )
        row = r.fetchone()
    if row:
        print(f"✅ {submission_id} 를 ERROR로 복구했습니다.")
    else:
        print(f"⚠️ {submission_id} 가 없거나 이미 완료/에러 상태입니다. (PROCESSING/VERIFYING만 갱신됨)")


if __name__ == "__main__":
    main()
