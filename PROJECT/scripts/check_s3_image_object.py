#!/usr/bin/env python3
"""
MinIO(S3)에 저장된 객체가 실제 이미지 바이너리인지 검사.
업로드는 됐는데 보이지 않을 때, Presigned PUT 시 본문이 바이너리가 아닐 수 있음.

사용: python PROJECT/scripts/check_s3_image_object.py <object_key>
예:   python PROJECT/scripts/check_s3_image_object.py receipts/08fc5d49-115e-4bed-9a2d-cdae128d0c54_33a3cf08_receipt-test.png
      python PROJECT/scripts/check_s3_image_object.py 08fc5d49-115e-4bed-9a2d-cdae128d0c54_33a3cf08_receipt-test.png
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

S3_ENDPOINT = os.getenv("S3_ENDPOINT")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_BUCKET = os.getenv("S3_BUCKET", "gems-receipts")

# PNG: 89 50 4E 47 0D 0A 1A 0A
PNG_SIG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
# JPEG: FF D8 FF
JPEG_SIG = bytes([0xFF, 0xD8, 0xFF])


def main():
    if len(sys.argv) < 2:
        print("사용법: python check_s3_image_object.py <object_key>")
        print("예: python check_s3_image_object.py receipts/08fc5d49-..._receipt-test.png")
        sys.exit(1)

    key = sys.argv[1].strip()
    if not key.startswith("receipts/"):
        key = f"receipts/{key}"

    if not S3_ENDPOINT or not S3_ACCESS_KEY or not S3_SECRET_KEY:
        print("❌ S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY 환경 변수를 설정하세요.")
        sys.exit(1)

    import boto3
    from botocore.exceptions import ClientError

    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )

    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
        body = resp["Body"].read()
        content_type = (resp.get("ContentType") or "").strip() or "(없음)"
        content_length = resp.get("ContentLength") or len(body)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        print(f"❌ 객체 조회 실패: {code} - {e}")
        sys.exit(1)

    print(f"Key: {key}")
    print(f"Size: {content_length} bytes")
    print(f"Content-Type (저장됨): {content_type}")
    print(f"첫 16바이트 (hex): {body[:16].hex() if len(body) >= 16 else body.hex()}")

    if body.startswith(PNG_SIG):
        print("✅ PNG 시그니처 일치 — 이미지 바이너리로 보임.")
    elif body.startswith(JPEG_SIG):
        print("✅ JPEG 시그니처 일치 — 이미지 바이너리로 보임.")
    elif body.startswith(b"{") or body.startswith(b"["):
        print("⚠️ JSON으로 보임. Presigned PUT 시 body를 파일 바이너리로 보내지 않고 JSON/FormData로 보낸 가능성.")
    elif body.startswith(b"---") or b"\r\n" in body[:200]:
        print("⚠️ multipart/form-data로 보임. Presigned PUT 시 body를 raw 파일만 보내야 함.")
    else:
        print("⚠️ 알 수 없는 형식. 이미지가 아닐 수 있음.")

    if content_length == 0:
        print("⚠️ 파일 크기 0 — 업로드 본문이 비어 있었을 수 있음.")


if __name__ == "__main__":
    main()
