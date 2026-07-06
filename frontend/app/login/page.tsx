"use client";

import { INSTITUTIONS } from "@/lib/api";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export default function Login() {
  const router = useRouter();
  const [selectedInst, setSelectedInst] = useState(INSTITUTIONS[0]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (localStorage.getItem("acn_institution")) {
      router.push("/");
    }
  }, [router]);

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    localStorage.setItem("acn_institution", selectedInst);
    window.location.href = "/";
  };

  return (
    <div
      className="min-h-screen flex"
      style={{ background: "#f0efeb", fontFamily: "Inter, system-ui, sans-serif" }}
    >
      {/* Left branding panel */}
      <div
        className="flex flex-col justify-between flex-1 px-14 py-12"
        style={{ background: "#1c1c1e" }}
      >
        {/* Logo */}
        <div className="flex items-center gap-3">
          <div
            className="flex h-10 w-10 items-center justify-center rounded-xl"
            style={{ background: "#c8a84b" }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#1c1c1e" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
          </div>
          <div>
            <div className="text-white font-bold text-sm tracking-widest uppercase">ACN</div>
            <div className="text-[#c8c8cc] text-sm font-medium tracking-wide">Compliance Console</div>
          </div>
        </div>

        {/* Hero copy */}
        <div>
          <h1 className="text-5xl font-black text-white leading-tight tracking-tight mb-4">
            The Power of<br />
            <span style={{ color: "#c8a84b" }}>Collaborative Compliance</span>
          </h1>
          <p className="text-[#9b9896] text-lg leading-relaxed">
            Graph analytics across institutional boundaries — detect what no single bank can see alone.
          </p>

          {/* Stats row */}
          <div className="grid grid-cols-2 gap-4 mt-8">
            {[
              { label: "Detection Lift", value: "+1.5×" },
              { label: "Recall @ 5% FPR", value: "56.0%" },
              { label: "Institutions", value: `${INSTITUTIONS.length}` },
              { label: "Model", value: "GNN v2.1" },
            ].map(({ label, value }) => (
              <div key={label} className="rounded-xl p-3" style={{ background: "#252528" }}>
                <div className="text-xs font-bold uppercase tracking-widest mb-1" style={{ color: "#9b9896" }}>{label}</div>
                <div className="text-xl font-black" style={{ color: "#c8a84b" }}>{value}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Feature list */}
        <div className="space-y-3">
          {[
            { icon: "M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9", label: "Collective intelligence across institutions" },
            { icon: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z", label: "Detect layering invisible to one bank" },
            { icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z", label: "Secure STR drafting without raw data sharing" },
          ].map(({ icon, label }) => (
            <div key={label} className="flex items-center gap-3">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg flex-shrink-0" style={{ background: "rgba(200,168,75,0.12)" }}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#c8a84b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d={icon} />
                </svg>
              </div>
              <span className="text-base font-medium" style={{ color: "#c8c8cc" }}>{label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Right login panel */}
      <div className="flex-1 flex flex-col items-center justify-center px-12 py-12" style={{ background: "#f0efeb" }}>
        <div className="w-full max-w-sm">
          <h2 className="text-2xl font-black text-[#1c1c1e] mb-1 tracking-tight">Join the network</h2>
          <p className="text-sm text-[#9b9896] mb-8">Select your institution to access the compliance console.</p>

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-xs font-bold uppercase tracking-widest text-[#9b9896] mb-2">
                Institution
              </label>
              <select
                id="institution-select"
                value={selectedInst}
                onChange={(e) => setSelectedInst(e.target.value)}
                className="w-full rounded-xl border px-4 py-3.5 text-sm font-medium text-[#1c1c1e] focus:outline-none focus:ring-2 transition-all appearance-none"
                style={{
                  background: "#fff",
                  border: "1.5px solid #e8e5e0",
                  boxShadow: "0 1px 4px rgba(0,0,0,0.04)",
                }}
                onFocus={(e) => { e.currentTarget.style.border = "1.5px solid #c8a84b"; e.currentTarget.style.boxShadow = "0 0 0 3px rgba(200,168,75,0.15)"; }}
                onBlur={(e) => { e.currentTarget.style.border = "1.5px solid #e8e5e0"; e.currentTarget.style.boxShadow = "0 1px 4px rgba(0,0,0,0.04)"; }}
              >
                {INSTITUTIONS.map((inst) => (
                  <option key={inst} value={inst}>{inst}</option>
                ))}
              </select>
            </div>

            <button
              id="login-btn"
              type="submit"
              disabled={loading}
              className="w-full rounded-xl py-3.5 text-sm font-bold uppercase tracking-wider transition-all hover:opacity-90 disabled:opacity-60"
              style={{ background: "#1c1c1e", color: "#fff" }}
            >
              {loading ? "Connecting…" : "Access Console"}
            </button>
          </form>

          {/* Info note */}
          <div className="mt-6 rounded-xl p-4" style={{ background: "#fdf6e3", border: "1px solid #e9d98a" }}>
            <div className="flex gap-3">
              <svg className="h-4 w-4 mt-0.5 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="#c8a84b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <p className="text-xs text-[#8a7030] leading-relaxed">
                You will only see accounts and data pertaining to your institution. Cross-bank nodes are pseudonymised by the consortium.
              </p>
            </div>
          </div>

          {/* Institutions grid */}
          <div className="mt-8">
            <div className="text-[10px] font-bold uppercase tracking-widest text-[#b8b5af] mb-3 text-center">
              Consortium Members
            </div>
            <div className="grid grid-cols-3 gap-2">
              {INSTITUTIONS.slice(0, 6).map((inst) => {
                const hue = [...inst].reduce((acc, c) => acc + c.charCodeAt(0), 0) % 360;
                const initials = inst.split(/[\s_]+/).filter(Boolean).map((w) => w[0]?.toUpperCase() ?? "").join("").slice(0, 2);
                return (
                  <button
                    key={inst}
                    type="button"
                    onClick={() => setSelectedInst(inst)}
                    className="flex flex-col items-center rounded-xl py-3 px-2 transition-all"
                    style={{
                      background: selectedInst === inst ? "#fff" : "transparent",
                      border: `1.5px solid ${selectedInst === inst ? "#c8a84b" : "#e8e5e0"}`,
                      boxShadow: selectedInst === inst ? "0 2px 8px rgba(200,168,75,0.15)" : "none",
                    }}
                  >
                    <div
                      className="flex h-8 w-8 items-center justify-center rounded-full text-white text-xs font-bold mb-1"
                      style={{ background: `hsl(${hue},42%,40%)` }}
                    >
                      {initials}
                    </div>
                    <span className="text-[9px] font-semibold text-[#6b6b70] text-center leading-tight truncate w-full px-1">{inst}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
