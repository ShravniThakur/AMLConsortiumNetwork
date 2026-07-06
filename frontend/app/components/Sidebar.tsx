"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CaseSummary, listCases } from "../../lib/api";

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [institution, setInstitution] = useState<string>("");
  const [initials, setInitials] = useState<string>("");
  const [cases, setCases] = useState<CaseSummary[]>([]);

  // All hooks before any conditional return
  useEffect(() => {
    const inst = localStorage.getItem("acn_institution") || "";
    setInstitution(inst);
    const words = inst.split(/[\s_]+/).filter(Boolean);
    setInitials(
      words.map((w) => w[0]?.toUpperCase() ?? "").join("").slice(0, 2) || "AC"
    );
    if (inst) {
      listCases(undefined, inst)
        .then(setCases)
        .catch(() => {});
    }
  }, []);

  // Hide on auth pages
  if (pathname === "/login") return null;

  const handleLogout = () => {
    localStorage.removeItem("acn_institution");
    router.push("/login");
  };

  const instHue = institution
    ? [...institution].reduce((acc, c) => acc + c.charCodeAt(0), 0) % 360
    : 200;

  // Queue stats
  const total        = cases.length;
  const openCount    = cases.filter((c) => c.status === "open").length;
  const escCount     = cases.filter((c) => c.status === "escalated").length;
  const filedCount   = cases.filter((c) => c.status === "filed").length;
  const dismissCount = cases.filter((c) => c.status === "dismissed").length;

  const HEALTH = [
    { label: "Open",      count: openCount,    color: "#c8a84b" },
    { label: "Escalated", count: escCount,      color: "#e05252" },
    { label: "Filed",     count: filedCount,    color: "#3cb371" },
    { label: "Dismissed", count: dismissCount,  color: "#888888" },
  ];

  return (
    <aside
      className="fixed left-0 top-0 h-screen flex flex-col z-40 sidebar-scroll"
      style={{
        width: "264px",
        background: "#1c1c1e",
        boxShadow: "2px 0 16px rgba(0,0,0,0.18)",
      }}
    >
      {/* ── Brand ── */}
      <div className="flex items-center gap-3 px-5 py-5 border-b border-[#2e2e31] flex-shrink-0">
        <div
          className="flex h-9 w-9 items-center justify-center rounded-lg flex-shrink-0"
          style={{ background: "#c8a84b" }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#1c1c1e" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          </svg>
        </div>
        <div>
          <div className="text-white font-bold text-base tracking-widest uppercase leading-tight">ACN</div>
          <div className="text-[#6b6b70] text-xs font-medium leading-tight">Compliance Console</div>
        </div>
      </div>

      {/* ── Institution ── */}
      {institution && (
        <div className="px-5 py-4 border-b border-[#2e2e31] flex-shrink-0">
          <div className="flex items-center gap-3">
            <div
              className="flex h-10 w-10 items-center justify-center rounded-full text-white font-bold text-sm flex-shrink-0"
              style={{ background: `hsl(${instHue},45%,38%)` }}
            >
              {initials}
            </div>
            <div className="min-w-0">
              <div className="text-xs text-[#6b6b70] font-semibold uppercase tracking-wider mb-0.5">Viewing as</div>
              <div className="text-white text-sm font-bold truncate">{institution}</div>
            </div>
          </div>
        </div>
      )}

      {/* ── Queue Health ── */}
      <div className="px-5 py-5 flex-shrink-0">
        {/* Stacked header */}
        <div className="mb-5">
          <div className="text-xs font-bold uppercase tracking-widest text-[#6b6b70] mb-1">Alerts</div>
          <div className="text-2xl font-black text-white leading-none">
            {total} <span className="text-sm font-semibold text-[#6b6b70]">total</span>
          </div>
        </div>

        {/* Stacked rows: label+count then full-width bar */}
        <div className="space-y-4">
          {HEALTH.map(({ label, count, color }) => (
            <div key={label}>
              {/* Label row */}
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2">
                  <div className="h-2 w-2 rounded-full flex-shrink-0" style={{ background: color }} />
                  <span className="text-sm font-semibold text-[#c8c8cc]">{label}</span>
                </div>
                <span className="text-sm font-bold text-white tabular-nums">{count}</span>
              </div>
              {/* Full-width bar below */}
              <div className="h-1.5 w-full rounded-full overflow-hidden" style={{ background: "#2e2e31" }}>
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${total > 0 ? Math.max((count / total) * 100, count > 0 ? 4 : 0) : 0}%`,
                    background: color,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>


      {/* ── Spacer ── */}
      <div className="flex-1" />

      {/* ── Bottom: Run Pipeline + Settings + Logout ── */}
      <div className="flex-shrink-0 border-t border-[#2e2e31]">
        {/* Pipeline */}
        <div className="px-4 py-3 border-b border-[#2e2e31]">
          <button
            onClick={async () => {
              try { await fetch("http://localhost:8000/pipeline/run", { method: "POST" }); } catch {}
            }}
            className="flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-xs font-bold uppercase tracking-wider transition-all hover:opacity-90"
            style={{ background: "rgba(200,168,75,0.10)", color: "#c8a84b", border: "1px solid rgba(200,168,75,0.25)" }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
            Run Pipeline
          </button>
        </div>

        {/* Log Out only */}
        <div className="px-3 py-3">
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-[#8e8e93] hover:bg-[#3a1a1a] hover:text-[#e05252] transition-all"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
            Log Out
          </button>
        </div>
      </div>
    </aside>
  );
}
