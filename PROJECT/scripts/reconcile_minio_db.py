#!/usr/bin/env python3
"""
MinIO receipts/ 객체와 DB submissions·receipt_items 정합성 점검.
- MinIO에만 있고 DB에 없는 submission_id → 고아 객체 (유효일: 관리자 설정 orphan_object_days, 기본 1일)
- DB에 submission은 있으나 receipt_items 없음 → 만료 후보 (유효일: 관리자 설정 expired_candidate_days, 기본 1일)

사용:
  python PROJECT/scripts/reconcile_minio_db.py [--days N] [--delete]
  --days N   미지정 시 DB judgment_rule_config에서 orphan_object_days, expired_candidate_days 읽음 (각 기본 1일)
             지정 시 N일로 고아/만료 후보 모두 적용
  --delete   고아 객체 실제 삭제 (미지정 시 dry-run만)
"""
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

S3_ENDPOINT = os.getenv("S3_ENDPOINT")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_BUCKET = os.getenv("S3_BUCKET", "gems-receipts")

# receipts/{uuid}_{8hex}_{filename} → uuid 추출
KEY_PATTERN = re.compile(r"^receipts/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})_")


def extract_submission_id(object_key: str):
    m = KEY_PATTERN.match(object_key)
    return m.group(1) if m else None


def main():
    do_delete = "--delete" in sys.argv
    orphan_days = 1
    expired_days = 1
    use_cli_days = False
    if "--days" in sys.argv:
        i = sys.argv.index("--days")
        if i + 1 < len(sys.argv):
            try:
                orphan_days = expired_days = int(sys.argv[i + 1])
                use_cli_days = True
            except ValueError:
                pass
    if not use_cli_days:
        # DB에서 관리자 설정값 읽기 (기본 1일)
        DATABASE_URL = os.getenv("DATABASE_URL")
        if DATABASE_URL:
            if DATABASE_URL.startswith("postgres://"):
                DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[11:]
            elif "postgresql://" in DATABASE_URL and "+psycopg2" not in DATABASE_URL:
                DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
            try:
                from sqlalchemy import create_engine, text
                engine = create_engine(DATABASE_URL)
                with engine.connect() as conn:
                    row = conn.execute(
                        text("SELECT orphan_object_days, expired_candidate_days FROM judgment_rule_config WHERE id = 1")
                    ).fetchone()
                if row:
                    orphan_days = max(1, int(row[0] or 1))
                    expired_days = max(1, int(row[1] or 1))
            except Exception:
                pass
    days = expired_days  # 만료 후보 기준일(보고용)

    if not all([S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY]):
        print("❌ S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY 설정 필요")
        sys.exit(1)

    import boto3
    from botocore.exceptions import ClientError

    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )

    # 1) MinIO receipts/ 목록 수집
    keys_by_sid: dict[str, list[dict]] = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="receipts/"):
        for obj in page.get("Contents") or []:
            key = obj.get("Key", "")
            sid = extract_submission_id(key)
            if not sid:
                continue
            if sid not in keys_by_sid:
                keys_by_sid[sid] = []
            keys_by_sid[sid].append({"Key": key, "LastModified": obj.get("LastModified"), "Size": obj.get("Size", 0)})

    if not keys_by_sid:
        print("MinIO receipts/ 아래 객체 없음.")
        return

    # 2) DB에서 해당 submission_id 목록·receipt_items 수·created_at 조회
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        print("❌ DATABASE_URL 설정 필요")
        sys.exit(1)
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[11:]
    elif "postgresql://" in DATABASE_URL and "+psycopg2" not in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

    from sqlalchemy import create_engine, text

    engine = create_engine(DATABASE_URL)
    sids = list(keys_by_sid.keys())
    cutoff_expired = (datetime.now(timezone.utc) - timedelta(days=expired_days)).replace(tzinfo=None)
    cutoff_orphan = (datetime.now(timezone.utc) - timedelta(days=orphan_days)).replace(tzinfo=None)

    # submission 존재 여부, created_at, status, receipt_items 개수
    db_info = {}
    batch = 200
    for i in range(0, len(sids), batch):
        chunk = sids[i : i + batch]
        placeholders = ", ".join(f":s{j}" for j in range(len(chunk)))
        with engine.connect() as conn:
            # submissions + item count
            rows = conn.execute(
                text(f"""
                    SELECT s.submission_id, s.created_at, s.status,
                           (SELECT COUNT(*) FROM receipt_items r WHERE r.submission_id = s.submission_id) AS item_count
                    FROM submissions s
                    WHERE s.submission_id IN ({placeholders})
                """),
                {f"s{j}": sid for j, sid in enumerate(chunk)},
            ).fetchall()
        for row in rows:
            db_info[row[0]] = {
                "created_at": row[1],
                "status": row[2],
                "item_count": row[3],
            }

    # 3) 분류
    only_minio = []
    pending_no_items = []
    completed_or_has_items = []

    for sid in sids:
        objs = keys_by_sid[sid]
        info = db_info.get(sid)
        if not info:
            only_minio.append((sid, objs))
            continue
        if (info["item_count"] or 0) == 0:
            pending_no_items.append((sid, objs, info))
        else:
            completed_or_has_items.append((sid, objs, info))

    # 4) 보고
    print(f"=== MinIO–DB 정합성 (고아 객체 유효일 {orphan_days}일, 만료 후보 유효일 {expired_days}일, 삭제={'예' if do_delete else '아니오(dry-run)'}) ===\n")
    print(f"MinIO 객체 수: {sum(len(v) for v in keys_by_sid.values())} (submission_id 수: {len(keys_by_sid)})\n")

    if only_minio:
        # 고아 객체 중 orphan_days 일 경과한 것만 삭제 대상
        def _obj_older(o, cutoff):
            lm = o.get("LastModified")
            if not lm:
                return True
            lm_naive = lm.replace(tzinfo=None) if hasattr(lm, "replace") and getattr(lm, "tzinfo", None) else lm
            return lm_naive < cutoff
        orphans_expired = [(sid, [o for o in objs if _obj_older(o, cutoff_orphan)]) for sid, objs in only_minio]
        orphans_expired = [(sid, objs) for sid, objs in orphans_expired if objs]
        n_expired = sum(len(objs) for _, objs in orphans_expired)
        print(f"[A] MinIO에만 있음 (DB에 submission 없음): {len(only_minio)}건 (그중 {orphan_days}일 경과 {n_expired}건)")
        for sid, objs in only_minio[:20]:
            print(f"  - {sid}  객체 {len(objs)}개")
        if len(only_minio) > 20:
            print(f"  ... 외 {len(only_minio) - 20}건")
        if do_delete and orphans_expired:
            for sid, objs in orphans_expired:
                for o in objs:
                    try:
                        s3.delete_object(Bucket=S3_BUCKET, Key=o["Key"])
                        print(f"  삭제: {o['Key']}")
                    except ClientError as e:
                        print(f"  삭제 실패 {o['Key']}: {e}")
        print()

    expired = []
    if pending_no_items:
        def _created_before(info, cutoff):
            c = info.get("created_at")
            if c is None:
                return False
            c_naive = c.replace(tzinfo=None) if getattr(c, "tzinfo", None) else c
            return c_naive < cutoff
        expired = [
            (sid, objs, info)
            for sid, objs, info in pending_no_items
            if _created_before(info, cutoff_expired)
        ]
        print(f"[B] DB에 submission 있으나 receipt_items 없음(Complete 미호출): {len(pending_no_items)}건")
        print(f"    그중 {expired_days}일 경과(만료 후보): {len(expired)}건")
        for sid, objs, info in expired[:10]:
            print(f"  - {sid}  created={info.get('created_at')}  객체 {len(objs)}개")
        if len(expired) > 10:
            print(f"  ... 외 {len(expired) - 10}건")
        print()

    print(f"[C] Complete 완료 또는 receipt_items 있음: {len(completed_or_has_items)}건")

    if not only_minio and not expired:
        print("\n고아/만료 후보 없음.")


if __name__ == "__main__":
    main()
