/** Dynamic Entry: 영수증 한 장 = 하나의 독립 객체 */
export type ReceiptEntryStatus = "IDLE" | "UPLOADING" | "COMPLETE" | "ERROR";

export interface ReceiptMetadata {
  /** 숙박(STAY) 필수 */
  location?: string;
  /** 관광(TOUR) 필수 */
  storeName?: string;
  payDate: string;
  amount: number;
  cardPrefix: string;
}

export interface ReceiptEntry {
  id: string;
  image: File | null;
  previewUrl: string | null;
  objectKey: string;
  receiptId: string | null;
  metadata: ReceiptMetadata;
  status: ReceiptEntryStatus;
  errorMessage?: string;
}

/** 제출 타입: 1:1 다중 엔트리 vs 1폼에 이미지 여러 장(향후 확장) */
export type SubmissionType = "MULTIPLE_ENTRIES" | "SINGLE_FORM_MULTIPLE_IMAGES";

export interface PresignedUrlResponse {
  uploadUrl: string;
  receiptId: string;
  objectKey: string;
}

export interface CompleteResponse {
  status: string;
  receiptId: string;
}

export interface StatusResponse {
  status: string | null;
  amount: number | null;
  failReason: string | null;
  rewardAmount: number;
  address: string | null;
  cardPrefix: string | null;
}
