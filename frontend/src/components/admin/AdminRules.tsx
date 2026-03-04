import { useState, useEffect, useCallback } from "react";
import {
  adminGetJudgmentRules,
  adminUpdateJudgmentRules,
  type JudgmentRuleConfig,
  type AdminAuth,
} from "../../api/admin";

const LABEL_POLICY: Record<string, string> = {
  AUTO_REGISTER: "자동 편입 (신뢰도 임계치 이상 시)",
  PENDING_NEW: "검수 대기 (관리자 승인 후 편입)",
};

interface AdminRulesProps {
  auth: AdminAuth | undefined;
}

export function AdminRules({ auth }: AdminRulesProps) {
  const [config, setConfig] = useState<JudgmentRuleConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<JudgmentRuleConfig>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await adminGetJudgmentRules(auth);
      setConfig(data);
      setDraft({});
    } catch (e) {
      setError(e instanceof Error ? e.message : "조회 실패");
    } finally {
      setLoading(false);
    }
  }, [auth]);

  useEffect(() => {
    load();
  }, [load]);

  const handleSave = async () => {
    if (!draft || Object.keys(draft).length === 0) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await adminUpdateJudgmentRules(draft, auth);
      setConfig(updated);
      setDraft({});
    } catch (e) {
      setError(e instanceof Error ? e.message : "저장 실패");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-100 bg-white p-6 shadow-sm">
        <p className="text-slate-500">판정 규칙 불러오는 중…</p>
      </div>
    );
  }

  const c = config!;
  const policy = (draft.unknown_store_policy ?? c.unknown_store_policy) as keyof typeof LABEL_POLICY;
  const threshold = draft.auto_register_threshold ?? c.auto_register_threshold;
  const gemini = draft.enable_gemini_classifier ?? c.enable_gemini_classifier;
  const minStay = draft.min_amount_stay ?? c.min_amount_stay;
  const minTour = draft.min_amount_tour ?? c.min_amount_tour;

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-100 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-800">판정 규칙 운영</h2>
        <p className="mt-1 text-sm text-slate-500">
          저장 시점 이후 신규 분석 건부터 적용됩니다. (기존 건 소급 적용 안 됨)
        </p>
        {error && (
          <div className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
        )}

        <div className="mt-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-600">미등록 상점 처리 정책</label>
            <div className="mt-2 flex gap-4">
              {(["AUTO_REGISTER", "PENDING_NEW"] as const).map((v) => (
                <label key={v} className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="policy"
                    checked={policy === v}
                    onChange={() => setDraft((p) => ({ ...p, unknown_store_policy: v }))}
                    className="h-4 w-4 text-primary focus:ring-primary"
                  />
                  <span className="text-sm">{LABEL_POLICY[v] ?? v}</span>
                </label>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-600">
              자동 편입 임계치 (0.0 ~ 1.0)
            </label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={threshold}
              onChange={(e) =>
                setDraft((p) => ({ ...p, auto_register_threshold: parseFloat(e.target.value) }))
              }
              className="mt-1 w-full"
            />
            <span className="ml-2 text-sm text-slate-600">{threshold}</span>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="gemini"
              checked={gemini}
              onChange={(e) => setDraft((p) => ({ ...p, enable_gemini_classifier: e.target.checked }))}
              className="h-4 w-4 rounded text-primary focus:ring-primary"
            />
            <label htmlFor="gemini" className="text-sm font-medium text-slate-600">
              Gemini 분류 사용 (신규 상점 업종 추론)
            </label>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-slate-600">STAY 최소 금액 (원)</label>
              <input
                type="number"
                min={0}
                value={minStay}
                onChange={(e) =>
                  setDraft((p) => ({ ...p, min_amount_stay: parseInt(e.target.value, 10) || 0 }))
                }
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600">TOUR 최소 금액 (원)</label>
              <input
                type="number"
                min={0}
                value={minTour}
                onChange={(e) =>
                  setDraft((p) => ({ ...p, min_amount_tour: parseInt(e.target.value, 10) || 0 }))
                }
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </div>
          </div>
        </div>

        <div className="mt-6 flex items-center gap-4">
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || Object.keys(draft).length === 0}
            className="min-h-[44px] rounded-lg bg-primary px-4 py-2 font-medium text-white shadow-sm hover:bg-primary-600 focus:ring-2 focus:ring-primary focus:ring-offset-2 disabled:opacity-50"
          >
            {saving ? "저장 중…" : "저장"}
          </button>
          {c.updated_at && (
            <span className="text-sm text-slate-500">
              최근 적용: {new Date(c.updated_at).toLocaleString("ko-KR")}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
