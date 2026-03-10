import { useState, useEffect, useCallback } from "react";
import {
  adminGetDashboardStats,
  adminGetRejectReasons,
  type AdminDashboardStats,
  type AdminRejectReasonItem,
  type AdminAuth,
} from "../../api/admin";

function formatDateRange(from: string, to: string): string {
  if (!from && !to) return "전체 기간";
  if (from && to) return `${from} ~ ${to}`;
  return from || to || "—";
}

interface AdminDashboardProps {
  auth: AdminAuth | undefined;
}

export function AdminDashboard({ auth }: AdminDashboardProps) {
  const [stats, setStats] = useState<AdminDashboardStats | null>(null);
  const [rejectReasons, setRejectReasons] = useState<AdminRejectReasonItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [campaignId, setCampaignId] = useState<string>("");
  const [from, setFrom] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() - 6);
    return d.toISOString().slice(0, 10);
  });
  const [to, setTo] = useState<string>(() => new Date().toISOString().slice(0, 10));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: { campaignId?: number; from?: string; to?: string } = {};
      if (from) params.from = from;
      if (to) params.to = to;
      const id = campaignId.trim() ? parseInt(campaignId, 10) : undefined;
      if (!isNaN(id as number)) params.campaignId = id;

      const [statsRes, reasonsRes] = await Promise.all([
        adminGetDashboardStats(params, auth),
        adminGetRejectReasons({ ...params, limit: 5 }, auth),
      ]);
      setStats(statsRes);
      setRejectReasons(reasonsRes);
    } catch (e) {
      setError(e instanceof Error ? e.message : "대시보드 조회 실패");
      setStats(null);
      setRejectReasons([]);
    } finally {
      setLoading(false);
    }
  }, [auth, campaignId, from, to]);

  useEffect(() => {
    load();
  }, [load]);

  const trendRate =
    stats && stats.yesterdayCount > 0
      ? (((stats.todayCount - stats.yesterdayCount) / stats.yesterdayCount) * 100).toFixed(1)
      : null;
  const maxDaily = stats?.dailyCounts?.length
    ? Math.max(...stats.dailyCounts.map((d) => d.count), 1)
    : 1;

  if (loading && !stats) {
    return (
      <div className="rounded-xl border border-slate-100 bg-white p-6 shadow-sm">
        <p className="text-slate-500">대시보드 불러오는 중…</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-100 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-800">대시보드</h2>
        <p className="mt-1 text-sm text-slate-500">
          수정된 데이터 기반 집계 (백엔드 요청사항 정리 §2.2, §4)
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <input
            type="number"
            placeholder="캠페인 ID (선택)"
            value={campaignId}
            onChange={(e) => setCampaignId(e.target.value)}
            className="w-32 rounded-lg border border-slate-200 px-3 py-2 text-sm"
            aria-label="캠페인 ID"
          />
          <input
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            aria-label="시작일"
          />
          <input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            aria-label="종료일"
          />
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="min-h-[44px] rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50"
          >
            {loading ? "조회 중…" : "조회"}
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-500">{formatDateRange(from, to)}</p>
        {error && (
          <div className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
        )}
      </div>

      {stats && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-slate-100 bg-white p-4 shadow-sm">
              <p className="text-sm font-medium text-slate-500">오늘 제출</p>
              <p className="mt-1 text-2xl font-semibold text-slate-800">{stats.todayCount}</p>
            </div>
            <div className="rounded-xl border border-slate-100 bg-white p-4 shadow-sm">
              <p className="text-sm font-medium text-slate-500">어제 제출</p>
              <p className="mt-1 text-2xl font-semibold text-slate-800">{stats.yesterdayCount}</p>
              {trendRate !== null && (
                <p
                  className={`mt-1 text-sm ${
                    Number(trendRate) >= 0 ? "text-emerald-600" : "text-red-600"
                  }`}
                >
                  전일 대비 {Number(trendRate) >= 0 ? "+" : ""}
                  {trendRate}%
                </p>
              )}
            </div>
            <div className="rounded-xl border border-slate-100 bg-white p-4 shadow-sm">
              <p className="text-sm font-medium text-slate-500">검수 대기 (MANUAL_REVIEW)</p>
              <p className="mt-1 text-2xl font-semibold text-amber-600">{stats.pendingCount}</p>
            </div>
            <div className="rounded-xl border border-slate-100 bg-white p-4 shadow-sm">
              <p className="text-sm font-medium text-slate-500">승인 금액 합계 (FIT)</p>
              <p className="mt-1 text-2xl font-semibold text-slate-800">
                {stats.approvedAmountSum.toLocaleString()}
              </p>
            </div>
          </div>

          <div className="rounded-xl border border-slate-100 bg-white p-6 shadow-sm">
            <h3 className="text-base font-semibold text-slate-800">유형별 건수 (byCategory)</h3>
            <div className="mt-3 flex flex-wrap gap-4">
              {Object.entries(stats.byCategory).length === 0 ? (
                <p className="text-sm text-slate-500">데이터 없음</p>
              ) : (
                Object.entries(stats.byCategory).map(([cat, count]) => (
                  <div key={cat} className="flex items-center gap-2">
                    <span className="rounded bg-slate-100 px-2 py-1 text-sm font-medium text-slate-700">
                      {cat === "UNKNOWN" ? "미분류" : cat}
                    </span>
                    <span className="text-sm text-slate-600">{count}건</span>
                  </div>
                ))
              )}
            </div>
          </div>

          {stats.dailyCounts.length > 0 && (
            <div className="rounded-xl border border-slate-100 bg-white p-6 shadow-sm">
              <h3 className="text-base font-semibold text-slate-800">일자별 제출 추이 (dailyCounts)</h3>
              <div className="mt-4 space-y-2">
                {stats.dailyCounts.map(({ date, count }) => (
                  <div key={date} className="flex items-center gap-3">
                    <span className="w-28 shrink-0 text-sm text-slate-600">{date}</span>
                    <div className="min-w-[120px] flex-1">
                      <div
                        className="h-6 rounded bg-blue-100"
                        style={{ width: `${(count / maxDaily) * 100}%`, minWidth: count ? "2rem" : 0 }}
                      />
                    </div>
                    <span className="w-12 text-right text-sm font-medium text-slate-700">
                      {count}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="rounded-xl border border-slate-100 bg-white p-6 shadow-sm">
            <h3 className="text-base font-semibold text-slate-800">주요 반려 사유 Top 5</h3>
            {rejectReasons.length === 0 ? (
              <p className="mt-3 text-sm text-slate-500">반려 사유 집계 없음 (API 연동 시 표시)</p>
            ) : (
              <ul className="mt-3 list-inside list-disc space-y-1 text-sm text-slate-700">
                {rejectReasons.map((r, i) => (
                  <li key={`${r.reason}-${i}`}>
                    <span className="font-medium">{r.reason || "(기타)"}</span>{" "}
                    <span className="text-slate-500">{r.count}건</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}

      <div className="rounded-xl border border-slate-100 bg-slate-50/50 p-6 shadow-sm">
        <h3 className="text-base font-semibold text-slate-800">데이터 자산화 대시보드 KPI (선택)</h3>
        <p className="mt-1 text-sm text-slate-500">
          백엔드 요청사항 정리 §11. BE에서 GET /api/v1/admin/dashboard/assetization 제공 시 실제 값으로 연동 가능.
        </p>
        <ul className="mt-3 space-y-1 text-sm text-slate-600">
          <li>OCR 인식 정확도 (Raw): —</li>
          <li>필드별 교정률: —</li>
          <li>신뢰도-정답 일치도: —</li>
          <li>골든 데이터셋 누적: —</li>
          <li>재학습 필요 비중: —</li>
        </ul>
      </div>
    </div>
  );
}
