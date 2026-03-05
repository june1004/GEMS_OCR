import { useState, useEffect, useCallback } from "react";
import {
  adminListSubmissions,
  adminGetSubmission,
  adminOverrideSubmission,
  adminResendCallback,
  adminVerifyCallback,
  type AdminCallbackVerifyResult,
  type AdminSubmissionListItem,
  type AdminAuth,
} from "../../api/admin";

interface AdminSubmissionsProps {
  auth: AdminAuth | undefined;
}

export function AdminSubmissions({ auth }: AdminSubmissionsProps) {
  const [items, setItems] = useState<AdminSubmissionListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [receiptIdQ, setReceiptIdQ] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [overrideStatus, setOverrideStatus] = useState("FIT");
  const [overrideReason, setOverrideReason] = useState("");
  const [overrideReward, setOverrideReward] = useState<number | "">("");
  const [resendCallbackFlag, setResendCallbackFlag] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [callbackVerifyResult, setCallbackVerifyResult] = useState<AdminCallbackVerifyResult | null>(
    null
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await adminListSubmissions(
        {
          status: status || undefined,
          receiptId: receiptIdQ || undefined,
          dateFrom: dateFrom || undefined,
          dateTo: dateTo || undefined,
          limit: 50,
          offset: 0,
        },
        auth
      );
      setItems(res.items);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "목록 조회 실패");
    } finally {
      setLoading(false);
    }
  }, [auth, status, receiptIdQ, dateFrom, dateTo]);

  useEffect(() => {
    load();
  }, [load]);

  const loadDetail = useCallback(
    async (id: string) => {
      setDetailId(id);
      setDetail(null);
      try {
        const res = await adminGetSubmission(id, auth);
        setDetail({ ...res.submission, ...res.statusPayload } as Record<string, unknown>);
      } catch {
        setDetail(null);
      }
    },
    [auth]
  );

  const handleOverride = async () => {
    if (!detailId) return;
    setSubmitting(true);
    setError(null);
    try {
      await adminOverrideSubmission(
        detailId,
        {
          status: overrideStatus,
          reason: overrideReason,
          override_reward_amount: overrideReward === "" ? undefined : overrideReward,
          resend_callback: resendCallbackFlag,
        },
        auth
      );
      setOverrideReason("");
      setOverrideReward("");
      load();
      loadDetail(detailId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Override 실패");
    } finally {
      setSubmitting(false);
    }
  };

  const handleResendCallback = async () => {
    if (!detailId) return;
    setSubmitting(true);
    setError(null);
    try {
      await adminResendCallback(detailId, {}, auth);
      loadDetail(detailId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "콜백 재전송 실패");
    } finally {
      setSubmitting(false);
    }
  };

  const handleVerifyCallback = async () => {
    if (!detailId) return;
    setSubmitting(true);
    setError(null);
    setCallbackVerifyResult(null);
    try {
      const res = await adminVerifyCallback(detailId, auth);
      setCallbackVerifyResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "콜백 검증 실패");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-100 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-800">신청(Submission) 검색</h2>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <input
            type="text"
            placeholder="receiptId"
            value={receiptIdQ}
            onChange={(e) => setReceiptIdQ(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            aria-label="receiptId"
          />
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            aria-label="상태"
          >
            <option value="">전체</option>
            <option value="FIT">FIT</option>
            <option value="UNFIT">UNFIT</option>
            <option value="PENDING_NEW">PENDING_NEW</option>
            <option value="VERIFYING">VERIFYING</option>
            <option value="PROCESSING">PROCESSING</option>
          </select>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            aria-label="시작일"
          />
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            aria-label="종료일"
          />
          <button
            type="button"
            onClick={load}
            className="min-h-[44px] rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200"
          >
            조회
          </button>
        </div>
        {error && (
          <div className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
        )}
      </div>

      {loading ? (
        <div className="rounded-xl border border-slate-100 bg-white p-6">
          <p className="text-slate-500">목록 불러오는 중…</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-100 bg-white shadow-sm">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50">
                <th className="p-2 font-medium text-slate-700">receiptId</th>
                <th className="p-2 font-medium text-slate-700">userUuid</th>
                <th className="p-2 font-medium text-slate-700">유형</th>
                <th className="p-2 font-medium text-slate-700">상태</th>
                <th className="p-2 font-medium text-slate-700">합계</th>
                <th className="p-2 font-medium text-slate-700">생성일시</th>
                <th className="p-2 font-medium text-slate-700">액션</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="p-6 text-center text-slate-500">
                    검색 결과 없음
                  </td>
                </tr>
              ) : (
                items.map((row) => (
                  <tr key={row.receiptId} className="border-b border-slate-100">
                    <td className="max-w-[180px] truncate font-mono text-xs p-2">{row.receiptId}</td>
                    <td className="max-w-[140px] truncate p-2">{row.userUuid}</td>
                    <td className="p-2">{row.project_type ?? "-"}</td>
                    <td className="p-2">{row.status ?? "-"}</td>
                    <td className="p-2">{row.total_amount?.toLocaleString() ?? 0}</td>
                    <td className="p-2 text-slate-600">{row.created_at ?? "-"}</td>
                    <td className="p-2">
                      <button
                        type="button"
                        onClick={() => loadDetail(row.receiptId)}
                        className="text-blue-600 hover:underline"
                      >
                        상세
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          <p className="p-2 text-sm text-slate-500">총 {total}건</p>
        </div>
      )}

      {detailId && (
        <div className="rounded-xl border border-slate-100 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-slate-800">상세: {detailId}</h3>
            <button
              type="button"
              onClick={() => setDetailId(null)}
              className="text-slate-500 hover:text-slate-700"
            >
              닫기
            </button>
          </div>
          {detail === null ? (
            <p className="mt-2 text-slate-500">로딩 중…</p>
          ) : (
            <>
              <pre className="mt-3 max-h-60 overflow-auto rounded bg-slate-50 p-3 text-xs">
                {JSON.stringify(detail, null, 2)}
              </pre>
              <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-slate-100 pt-4">
                <div>
                  <label className="block text-sm text-slate-600">Override 상태</label>
                  <select
                    value={overrideStatus}
                    onChange={(e) => setOverrideStatus(e.target.value)}
                    className="mt-1 rounded-lg border border-slate-200 px-3 py-2 text-sm"
                  >
                    <option value="FIT">FIT</option>
                    <option value="UNFIT">UNFIT</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm text-slate-600">사유</label>
                  <input
                    type="text"
                    value={overrideReason}
                    onChange={(e) => setOverrideReason(e.target.value)}
                    placeholder="관리자 검토 승인"
                    className="mt-1 rounded-lg border border-slate-200 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm text-slate-600">리워드(원, 선택)</label>
                  <input
                    type="number"
                    value={overrideReward === "" ? "" : overrideReward}
                    onChange={(e) =>
                      setOverrideReward(
                        e.target.value === "" ? "" : parseInt(e.target.value, 10) || 0
                      )
                    }
                    className="mt-1 w-28 rounded-lg border border-slate-200 px-3 py-2 text-sm"
                  />
                </div>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={resendCallbackFlag}
                    onChange={(e) => setResendCallbackFlag(e.target.checked)}
                  />
                  <span className="text-sm">Override 후 콜백 재전송</span>
                </label>
                <button
                  type="button"
                  onClick={handleOverride}
                  disabled={submitting}
                  className="min-h-[44px] rounded-lg bg-blue-500 px-4 py-2 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-50"
                >
                  {submitting ? "처리 중…" : "Override 적용"}
                </button>
                <button
                  type="button"
                  onClick={handleResendCallback}
                  disabled={submitting}
                  className="min-h-[44px] rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50"
                >
                  콜백만 재전송
                </button>
                <button
                  type="button"
                  onClick={handleVerifyCallback}
                  disabled={submitting}
                  className="min-h-[44px] rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                >
                  콜백 검증(즉시 송출)
                </button>
              </div>
              {callbackVerifyResult && (
                <div className="mt-3 rounded-lg border border-slate-100 bg-slate-50 p-3 text-xs text-slate-700">
                  <div className="font-medium text-slate-800">콜백 검증 결과</div>
                  <pre className="mt-2 overflow-auto">{JSON.stringify(callbackVerifyResult, null, 2)}</pre>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
