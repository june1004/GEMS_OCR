import requests
import time
import os

# 1. 환경 설정
BASE_URL = "https://api.nanum.online"
TEST_IMAGE_PATH = "my_receipt.jpg"  # 테스트용 실제 이미지 파일 경로
USER_UUID = "test-user-0001"

def test_receipt_process(receipt_type="TOUR"):
    print(f"--- [{receipt_type}] 프로세스 테스트 시작 ---")
    
    # [Step 1] Presigned URL 요청
    print("[1/4] Presigned URL 발급 요청 중...")
    params = {
        "fileName": os.path.basename(TEST_IMAGE_PATH),
        "contentType": "image/jpeg",
        "userUuid": USER_UUID,
        "type": receipt_type
    }
    res_url = requests.post(f"{BASE_URL}/api/v1/receipts/presigned-url", params=params)
    if res_url.status_code != 200:
        print("발급 실패:", res_url.text)
        return

    data = res_url.json()
    upload_url = data["uploadUrl"]
    receipt_id = data["receiptId"]
    object_key = data["objectKey"]
    print(f"성공! ID: {receipt_id}")

    # [Step 2] 스토리지(MinIO)에 이미지 직접 업로드
    print("[2/4] 이미지 업로드 중...")
    with open(TEST_IMAGE_PATH, 'rb') as f:
        res_upload = requests.put(upload_url, data=f, headers={'Content-Type': 'image/jpeg'})
    
    if res_upload.status_code != 200:
        print("업로드 실패:", res_upload.status_code)
        return
    print("업로드 성공!")

    # [Step 3] 분석 요청 (비즈니스 데이터 전송)
    print("[3/4] 백엔드 분석 요청 전송...")
    payload = {
        "receiptId": receipt_id,
        "userUuid": USER_UUID,
        "type": receipt_type,
        "data": {
            "storeName": "강원맛식당" if receipt_type == "TOUR" else None,
            "location": "춘천시" if receipt_type == "STAY" else None,
            "payDate": "2026-05-20",
            "amount": 55000 if receipt_type == "TOUR" else 75000,
            "cardPrefix": "1234",
            "receiptImageKeys": [object_key] if receipt_type == "TOUR" else None,
            "receiptImageKey": object_key if receipt_type == "STAY" else None
        }
    }
    # None 값 제거
    payload["data"] = {k: v for k, v in payload["data"].items() if v is not None}
    
    res_complete = requests.post(f"{BASE_URL}/api/v1/receipts/complete", json=payload)
    print("응답:", res_complete.json())

    # [Step 4] 결과 폴링 (Polling)
    print("[4/4] 최종 결과 대기 중 (최대 30초)...")
    for _ in range(10):  # 3초 간격으로 10번 시도
        time.sleep(3)
        res_status = requests.get(f"{BASE_URL}/api/v1/receipts/{receipt_id}/status")
        result = res_status.json()
        
        status = result.get("status")
        print(f"현재 상태: {status}")
        
        if status in ["FIT", "UNFIT", "DUPLICATE", "ERROR"]:
            print("--- 최종 결과 확인 ---")
            print(result)
            break
    else:
        print("시간 초과: 분석이 지연되고 있습니다.")

if __name__ == "__main__":
    # 실제 이미지가 있는지 확인 후 실행
    if os.path.exists(TEST_IMAGE_PATH):
        test_receipt_process("TOUR")  # 또는 "STAY"
    else:
        print(f"에러: '{TEST_IMAGE_PATH}' 파일이 필요합니다.")