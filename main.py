import os
import uuid
import boto3
from fastapi import FastAPI
from botocore.config import Config

app = FastAPI()

# S3(MinIO) 클라이언트 설정
s3_client = boto3.client(
    's3',
    endpoint_url=os.getenv('S3_ENDPOINT'), # https://storage-api.nanum.online
    aws_access_key_id=os.getenv('S3_ACCESS_KEY'), # gems_master
    aws_secret_access_key=os.getenv('S3_SECRET_KEY'),
    config=Config(signature_version='s3v4')
)

@app.post("/api/v1/receipts/presigned-url")
async def get_presigned_url(fileName: str, contentType: str):
    """1단계: 업로드용 Presigned URL 발행"""
    receiptId = str(uuid.uuid4()) # UUID 생성
    objectKey = f"receipts/{receiptId}_{fileName}"
    
    url = s3_client.generate_presigned_url(
        'put_object',
        Params={
            'Bucket': os.getenv('S3_BUCKET'), # gems-receipts
            'Key': objectKey,
            'ContentType': contentType
        },
        ExpiresIn=600 # 10분(600초) 유효
    )
    
    return {"uploadUrl": url, "receiptId": receiptId, "objectKey": objectKey}