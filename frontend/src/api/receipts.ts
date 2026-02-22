import type {
  PresignedUrlResponse,
  CompleteResponse,
  StatusResponse,
} from "../types";

const API_BASE =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function getPresignedUrl(
  fileName: string,
  contentType: string,
  userUuid: string,
  type: "STAY" | "TOUR"
): Promise<PresignedUrlResponse> {
  const params = new URLSearchParams({
    fileName,
    contentType,
    userUuid,
    type,
  });
  const res = await fetch(`${API_BASE}/api/v1/receipts/presigned-url?${params}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/** Presigned URL로 이미지 PUT 업로드 */
export async function uploadToStorage(
  uploadUrl: string,
  file: File
): Promise<void> {
  const res = await fetch(uploadUrl, {
    method: "PUT",
    body: file,
    headers: { "Content-Type": file.type },
  });
  if (!res.ok) throw new Error(`업로드 실패: ${res.status}`);
}

/** 1) Presigned 발급 + 2) 스토리지 업로드 한 번에 */
export async function uploadReceiptImage(
  file: File,
  userUuid: string,
  type: "STAY" | "TOUR"
): Promise<{ receiptId: string; objectKey: string }> {
  const name = file.name || "image.jpg";
  const contentType = file.type || "image/jpeg";
  const { uploadUrl, receiptId, objectKey } = await getPresignedUrl(
    name,
    contentType,
    userUuid,
    type
  );
  await uploadToStorage(uploadUrl, file);
  return { receiptId, objectKey };
}

/** 3단계: 정보 제출 및 분석 요청 (complete) */
export async function submitComplete(
  receiptId: string,
  userUuid: string,
  type: "STAY" | "TOUR",
  data: Record<string, unknown>,
  campaignId: number = 1
): Promise<CompleteResponse> {
  const res = await fetch(`${API_BASE}/api/v1/receipts/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      receiptId,
      userUuid,
      type,
      campaignId,
      data,
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/** 4단계: 결과 조회 (Polling) */
export async function getStatus(receiptId: string): Promise<StatusResponse> {
  const res = await fetch(
    `${API_BASE}/api/v1/receipts/status/${encodeURIComponent(receiptId)}`
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
