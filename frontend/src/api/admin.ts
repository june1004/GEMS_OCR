/**
 * 관리자 API 클라이언트 (FastAPI /api/v1/admin/* 연동)
 * ADMIN_PORTAL_GUIDE.md 및 Swagger 태그(Admin - Rules/Stores/Submissions) 기준.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export type AdminAuth = {
  adminKey?: string;
  actor?: string;
};

export function buildAdminHeaders(auth?: AdminAuth): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (auth?.adminKey) h["X-Admin-Key"] = auth.adminKey;
  if (auth?.actor) h["X-Admin-Actor"] = auth.actor;
  return h;
}

// --- 판정 규칙
export type JudgmentRuleConfig = {
  unknown_store_policy: "AUTO_REGISTER" | "PENDING_NEW";
  auto_register_threshold: number;
  enable_gemini_classifier: boolean;
  min_amount_stay: number;
  min_amount_tour: number;
  updated_at?: string;
};

export async function adminGetJudgmentRules(auth?: AdminAuth): Promise<JudgmentRuleConfig> {
  const r = await fetch(`${API_BASE}/api/v1/admin/rules/judgment`, {
    headers: buildAdminHeaders(auth),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function adminUpdateJudgmentRules(
  body: Partial<JudgmentRuleConfig>,
  auth?: AdminAuth
): Promise<JudgmentRuleConfig> {
  const r = await fetch(`${API_BASE}/api/v1/admin/rules/judgment`, {
    method: "PUT",
    headers: buildAdminHeaders(auth),
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// --- 신규 상점 후보군
export type CandidateStoreItem = {
  candidate_id: string;
  store_name?: string | null;
  biz_num?: string | null;
  address?: string | null;
  tel?: string | null;
  occurrence_count: number;
  predicted_category?: string | null;
  first_detected_at?: string | null;
  recent_receipt_id?: string | null;
  status: string;
};

export type CandidatesListResponse = {
  total_candidates: number;
  items: CandidateStoreItem[];
};

export async function adminListCandidates(
  params: { city_county?: string; min_occurrence?: number; sort_by?: "occurrence_count" | "created_at" },
  auth?: AdminAuth
): Promise<CandidatesListResponse> {
  const qs = new URLSearchParams();
  if (params.city_county) qs.set("city_county", params.city_county);
  if (params.min_occurrence != null) qs.set("min_occurrence", String(params.min_occurrence));
  if (params.sort_by) qs.set("sort_by", params.sort_by);
  const r = await fetch(`${API_BASE}/api/v1/admin/stores/candidates?${qs.toString()}`, {
    headers: buildAdminHeaders(auth),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function adminApproveCandidates(
  body: { candidate_ids: string[]; target_category: string; is_premium?: boolean },
  auth?: AdminAuth
): Promise<{ approved_count: number; failed_ids: string[] }> {
  const r = await fetch(`${API_BASE}/api/v1/admin/stores/candidates/approve`, {
    method: "POST",
    headers: buildAdminHeaders(auth),
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// --- 신청(Submission) 검색/상세
export type AdminSubmissionListItem = {
  receiptId: string;
  userUuid: string;
  project_type?: string | null;
  status?: string | null;
  total_amount: number;
  created_at?: string | null;
};

export type AdminSubmissionListResponse = {
  total: number;
  items: AdminSubmissionListItem[];
};

export type AdminSubmissionDetailResponse = {
  receiptId: string;
  submission: Record<string, unknown>;
  statusPayload: Record<string, unknown>;
};

export async function adminListSubmissions(
  params: {
    status?: string;
    userUuid?: string;
    receiptId?: string;
    dateFrom?: string;
    dateTo?: string;
    limit?: number;
    offset?: number;
  },
  auth?: AdminAuth
): Promise<AdminSubmissionListResponse> {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v == null || v === "") return;
    qs.set(k, String(v));
  });
  const r = await fetch(`${API_BASE}/api/v1/admin/submissions?${qs.toString()}`, {
    headers: buildAdminHeaders(auth),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function adminGetSubmission(
  receiptId: string,
  auth?: AdminAuth
): Promise<AdminSubmissionDetailResponse> {
  const r = await fetch(`${API_BASE}/api/v1/admin/submissions/${encodeURIComponent(receiptId)}`, {
    headers: buildAdminHeaders(auth),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// --- 증거(영수증) 이미지
export type AdminReceiptImagesResponse = {
  receiptId: string;
  expiresIn?: number;
  items: Array<{
    item_id: string;
    doc_type?: string | null;
    image_key: string;
    image_url: string;
  }>;
};

export async function adminGetReceiptImages(
  receiptId: string,
  auth?: AdminAuth
): Promise<AdminReceiptImagesResponse> {
  const r = await fetch(`${API_BASE}/api/v1/admin/receipts/${encodeURIComponent(receiptId)}/images`, {
    headers: buildAdminHeaders(auth),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// --- Override / 콜백 재전송
export async function adminOverrideSubmission(
  receiptId: string,
  body: { status: string; reason: string; override_reward_amount?: number; resend_callback?: boolean },
  auth?: AdminAuth
): Promise<{ receiptId: string; previous_status: string; new_status: string; updated_at: string }> {
  const r = await fetch(`${API_BASE}/api/v1/admin/submissions/${encodeURIComponent(receiptId)}/override`, {
    method: "POST",
    headers: buildAdminHeaders(auth),
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function adminResendCallback(
  receiptId: string,
  body?: { target_url?: string },
  auth?: AdminAuth
): Promise<{ receiptId: string; sent: boolean }> {
  const r = await fetch(
    `${API_BASE}/api/v1/admin/submissions/${encodeURIComponent(receiptId)}/callback/resend`,
    {
      method: "POST",
      headers: buildAdminHeaders(auth),
      body: JSON.stringify(body ?? {}),
    }
  );
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type AdminCallbackVerifyResult =
  | { skipped: true; reason: string }
  | { receiptId: string; url: string; purpose: string; ok: boolean; status: number; elapsed_ms: number }
  | { receiptId: string; url: string; purpose: string; ok: false; error: string };

export async function adminVerifyCallback(
  receiptId: string,
  auth?: AdminAuth
): Promise<AdminCallbackVerifyResult> {
  const r = await fetch(
    `${API_BASE}/api/v1/admin/submissions/${encodeURIComponent(receiptId)}/callback/verify`,
    {
      method: "POST",
      headers: buildAdminHeaders(auth),
      body: JSON.stringify({}),
    }
  );
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
