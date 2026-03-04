import { useState, useEffect, useCallback } from "react";
import {
  adminListCandidates,
  adminApproveCandidates,
  adminGetReceiptImages,
  type CandidateStoreItem,
  type AdminAuth,
} from "../../api/admin";

interface AdminCandidatesProps {
  auth: AdminAuth | undefined;
}

export function AdminCandidates({ auth }: AdminCandidatesProps) {
  const [items, setItems] = useState<CandidateStoreItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cityCounty, setCityCounty] = useState("");
  const [minOccurrence, setMinOccurrence] = useState<number | "">("");
  const [sortBy, setSortBy] = useState<"occurrence_count" | "created_at">("occurrence_count");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [approving, setApproving] = useState(false);
  const [targetCategory, setTargetCategory] = useState("TOUR_FOOD");
  const [evidenceReceiptId, setEvidenceReceiptId] = useState<string | null>(null);
  const [evidenceUrls, setEvidenceUrls] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await adminListCandidates(
        {
          city_county: cityCounty || undefined,
          min_occurrence: minOccurrence === "" ? undefined : Number(minOccurrence),
          sort_by: sortBy,
        },
        auth
      );
      setItems(res.items);
      setTotal(res.total_candidates);
    } catch (e) {
      setError(e instanceof Error ? e.message : "목록 조회 실패");
    } finally {
      setLoading(false);
    }
  }, [auth, cityCounty, minOccurrence, sortBy]);

  useEffect(() => {
    load();
  }, [load]);

  const handleApprove = async () => {
    if (selected.size === 0) return;
    setApproving(true);
    setError(null);
    try {
      await adminApproveCandidates(
        { candidate_ids: Array.from(selected), target_category: targetCategory },
        auth
      );
      setSelected(new Set());
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "승인 처리 실패");
    } finally {
      setApproving(false);
    }
  };

  const showEvidence = async (receiptId: string) => {
    setEvidenceReceiptId(receiptId);
    setEvidenceUrls([]);
    try {
      const res = await adminGetReceiptImages(receiptId, auth);
      setEvidenceUrls(res.items.map((i) => i.image_url));
    } catch {
      setEvidenceUrls([]);
    }
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-100 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-800">신규 상점 후보군</h2>
        <p className="mt-1 text-sm text-slate-500">
          빈도순 정렬 권장. 선택 후 승인 시 마스터 데이터로 편입됩니다.
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <input
            type="text"
            placeholder="시군구 (예: 춘천시)"
            value={cityCounty}
            onChange={(e) => setCityCounty(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            aria-label="시군구"
          />
          <input
            type="number"
            placeholder="최소 발견 횟수"
            min={0}
            value={minOccurrence === "" ? "" : minOccurrence}
            onChange={(e) =>
              setMinOccurrence(e.target.value === "" ? "" : parseInt(e.target.value, 10) || 0)
            }
            className="w-28 rounded-lg border border-slate-200 px-3 py-2 text-sm"
            aria-label="최소 발견 횟수"
          />
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as "occurrence_count" | "created_at")}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            aria-label="정렬"
          >
            <option value="occurrence_count">빈도순</option>
            <option value="created_at">최신순</option>
          </select>
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

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="text-sm text-slate-600">승인 시 카테고리:</span>
          <select
            value={targetCategory}
            onChange={(e) => setTargetCategory(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
          >
            <option value="TOUR_FOOD">TOUR_FOOD</option>
            <option value="TOUR_SIGHTSEEING">TOUR_SIGHTSEEING</option>
            <option value="STAY_ACCOMMODATION">STAY_ACCOMMODATION</option>
          </select>
          <button
            type="button"
            onClick={handleApprove}
            disabled={approving || selected.size === 0}
            className="min-h-[44px] rounded-lg bg-blue-500 px-4 py-2 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-50"
          >
            {approving ? "처리 중…" : `선택 승인 (${selected.size}건)`}
          </button>
        </div>
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
                <th className="p-2 w-10" />
                <th className="p-2 font-medium text-slate-700">상호명</th>
                <th className="p-2 font-medium text-slate-700">사업자번호</th>
                <th className="p-2 font-medium text-slate-700">주소</th>
                <th className="p-2 font-medium text-slate-700">빈도</th>
                <th className="p-2 font-medium text-slate-700">상태</th>
                <th className="p-2 font-medium text-slate-700">액션</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="p-6 text-center text-slate-500">
                    후보가 없습니다.
                  </td>
                </tr>
              ) : (
                items.map((row) => (
                  <tr key={row.candidate_id} className="border-b border-slate-100">
                    <td className="p-2">
                      <input
                        type="checkbox"
                        checked={selected.has(row.candidate_id)}
                        onChange={() => toggleSelect(row.candidate_id)}
                        aria-label={`${row.store_name ?? ""} 선택`}
                      />
                    </td>
                    <td className="p-2">{row.store_name ?? "-"}</td>
                    <td className="p-2 font-mono text-xs">{row.biz_num ?? "-"}</td>
                    <td className="max-w-[200px] truncate p-2">{row.address ?? "-"}</td>
                    <td className="p-2">{row.occurrence_count}</td>
                    <td className="p-2">{row.status}</td>
                    <td className="p-2">
                      {row.recent_receipt_id && (
                        <button
                          type="button"
                          onClick={() => showEvidence(row.recent_receipt_id!)}
                          className="text-blue-600 hover:underline"
                        >
                          증거 보기
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          <p className="p-2 text-sm text-slate-500">총 {total}건</p>
        </div>
      )}

      {evidenceReceiptId && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={() => setEvidenceReceiptId(null)}
          role="dialog"
          aria-label="증거 이미지"
        >
          <div
            className="max-h-[90vh] max-w-2xl overflow-auto rounded-xl bg-white p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between">
              <h3 className="font-medium">증거 이미지 (receiptId: {evidenceReceiptId})</h3>
              <button
                type="button"
                onClick={() => setEvidenceReceiptId(null)}
                className="text-slate-500 hover:text-slate-700"
              >
                닫기
              </button>
            </div>
            <div className="mt-3 space-y-2">
              {evidenceUrls.length === 0 ? (
                <p className="text-sm text-slate-500">이미지 없음 또는 조회 실패</p>
              ) : (
                evidenceUrls.map((url, i) => (
                  <img key={i} src={url} alt={`증거 ${i + 1}`} className="max-w-full rounded" />
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
