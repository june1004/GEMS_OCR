import { useState, useEffect } from "react";
import type { AdminAuth } from "./api/admin";
import { AdminDashboard } from "./components/admin/AdminDashboard";
import { AdminRules } from "./components/admin/AdminRules";
import { AdminCandidates } from "./components/admin/AdminCandidates";
import { AdminSubmissions } from "./components/admin/AdminSubmissions";

type AdminTab = "dashboard" | "rules" | "candidates" | "submissions";

function getTabFromHash(): AdminTab {
  const h = window.location.hash.replace("#admin", "").replace(/^\/+/, "").split("/")[0] || "dashboard";
  if (["dashboard", "rules", "candidates", "submissions"].includes(h)) return h as AdminTab;
  return "dashboard";
}

export function AdminApp() {
  const [tab, setTab] = useState<AdminTab>(getTabFromHash);
  const [auth, setAuth] = useState<AdminAuth>(() => ({
    adminKey: localStorage.getItem("admin_api_key") ?? undefined,
    actor: localStorage.getItem("admin_actor") ?? undefined,
  }));

  useEffect(() => {
    const onHash = () => setTab(getTabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const setAdminKey = (v: string) => {
    if (v) localStorage.setItem("admin_api_key", v);
    else localStorage.removeItem("admin_api_key");
    setAuth((a) => ({ ...a, adminKey: v || undefined }));
  };
  const setActor = (v: string) => {
    if (v) localStorage.setItem("admin_actor", v);
    else localStorage.removeItem("admin_actor");
    setAuth((a) => ({ ...a, actor: v || undefined }));
  };

  const nav = (t: AdminTab) => {
    if (t === "dashboard") window.location.hash = "#admin";
    else if (t === "rules") window.location.hash = "#admin/rules";
    else window.location.hash = `#admin/${t}`;
  };

  return (
    <div className="min-h-screen bg-slate-50 print:hidden">
      <header className="border-b border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3">
          <h1 className="text-lg font-semibold text-slate-800">관리자 (GEMS OCR)</h1>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <input
              type="password"
              placeholder="Admin Key (선택)"
              value={auth.adminKey ?? ""}
              onChange={(e) => setAdminKey(e.target.value)}
              className="rounded border border-slate-200 px-2 py-1"
              aria-label="Admin Key"
            />
            <input
              type="text"
              placeholder="담당자"
              value={auth.actor ?? ""}
              onChange={(e) => setActor(e.target.value)}
              className="rounded border border-slate-200 px-2 py-1"
              aria-label="담당자"
            />
            <a
              href="#"
              className="text-blue-600 hover:underline"
              onClick={(e) => {
                e.preventDefault();
                window.location.hash = "";
              }}
            >
              사용자 화면으로
            </a>
          </div>
        </div>
        <nav className="mt-3 flex gap-2">
          {(["dashboard", "rules", "candidates", "submissions"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => nav(t)}
              className={`min-h-[44px] rounded-lg px-3 py-1.5 text-sm font-medium ${
                tab === t ? "bg-blue-500 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
              }`}
            >
              {t === "dashboard"
                ? "대시보드"
                : t === "rules"
                  ? "판정 규칙"
                  : t === "candidates"
                    ? "후보 상점"
                    : "신청 검색"}
            </button>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">
        {tab === "dashboard" && <AdminDashboard auth={auth} />}
        {tab === "rules" && <AdminRules auth={auth} />}
        {tab === "candidates" && <AdminCandidates auth={auth} />}
        {tab === "submissions" && <AdminSubmissions auth={auth} />}
      </main>
    </div>
  );
}
