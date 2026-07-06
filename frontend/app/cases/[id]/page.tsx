"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { CaseDetail, decide, getCase, INSTITUTIONS } from "../../../lib/api";
import dynamic from "next/dynamic";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

const DECISIONS = [
  { key: "file",     label: "File SAR",  style: { background: "#3cb371", color: "#fff", border: "1.5px solid #267a4e" } },
  { key: "escalate", label: "Escalate",  style: { background: "#c8a84b", color: "#fff", border: "1.5px solid #8a7030" } },
  { key: "dismiss",  label: "Dismiss",   style: { background: "#fff",    color: "#6b6b70", border: "1.5px solid #e8e5e0" } },
];

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-2xl p-6 ${className}`}
      style={{ background: "#fff", boxShadow: "0 2px 12px rgba(0,0,0,0.06), 0 1px 3px rgba(0,0,0,0.04)" }}
    >
      {children}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] font-bold uppercase tracking-widest text-[#9b9896] mb-3">{children}</div>
  );
}

export default function CasePage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const [institution, setInstitution] = useState<string>("");
  const containerRef = useRef<HTMLDivElement>(null);
  const [graphDim, setGraphDim] = useState({ width: 800, height: 380 });

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (let entry of entries) {
        setGraphDim({ width: entry.contentRect.width, height: entry.contentRect.height });
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);
  const [data, setData] = useState<CaseDetail | null>(null);
  const [narrative, setNarrative] = useState("");
  const [officer, setOfficer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [msgType, setMsgType] = useState<"success" | "error">("success");

  const load = useCallback(() => {
    if (!institution) return;
    getCase(params.id, institution, true)
      .then((c) => {
        setData(c);
        setNarrative(c.draft_str?.narrative ?? "");
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, [params.id, institution]);

  useEffect(() => {
    const inst = localStorage.getItem("acn_institution");
    if (!inst) { router.push("/login"); return; }
    setInstitution(inst);
  }, [router]);

  useEffect(() => { if (institution) load(); }, [load, institution]);

  async function onDecide(decision: string) {
    if (!officer.trim()) {
      setMsg("Enter the reviewing officer's name first.");
      setMsgType("error");
      return;
    }
    try {
      await decide(params.id, decision, officer.trim());
      setMsg(`✓ Decision recorded: ${decision}.`);
      setMsgType("success");
      load();
    } catch (e) {
      setMsg(`Failed: ${e}`);
      setMsgType("error");
    }
  }

  function downloadSAR() {
    const blob = new Blob([narrative], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `SAR_${params.id}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  if (error) return (
    <div className="px-7 py-7">
      <div className="rounded-xl border border-[#f0b0b0] bg-[#fdeaea] px-4 py-3 text-sm text-[#b03a3a]">
        {error}. <Link href="/" className="underline font-semibold">← Back to queue</Link>
      </div>
    </div>
  );

  if (!data) return (
    <div className="flex items-center justify-center h-64 text-sm text-[#9b9896]">
      <svg className="animate-spin h-5 w-5 mr-2 text-[#c8a84b]" fill="none" viewBox="0 0 24 24">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
      </svg>
      Loading case…
    </div>
  );

  const scoreColor = (data.score ?? 0) >= 0.8 ? "#e05252" : (data.score ?? 0) >= 0.5 ? "#c8a84b" : "#3cb371";

  return (
    <div className="px-7 py-7 fade-in-up space-y-5 mr-4">

      {/* Top row: back + title */}
      <div className="flex items-start justify-between">
        <div>
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#9b9896] hover:text-[#c8a84b] transition-colors mb-2"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
            Alert Queue
          </Link>
          <h1 className="text-2xl font-black text-[#1c1c1e] tracking-tight capitalize">
            {data.pattern.replace(/_/g, " ")}
          </h1>
          <div className="flex items-center gap-3 mt-2 text-xs text-[#9b9896] font-medium">
            <span>
              Score:{" "}
              <span className="font-black" style={{ color: scoreColor }}>
                {data.score?.toFixed(2)}
              </span>
            </span>
            <span className="text-[#d1cec9]">·</span>
            <span className="uppercase font-semibold">{data.status}</span>
            <span className="text-[#d1cec9]">·</span>
            <span>{data.institutions.join(", ")}</span>
          </div>
        </div>
        <div
          className="flex flex-col items-end gap-1 rounded-xl px-4 py-3"
          style={{ background: "#fff", boxShadow: "0 2px 8px rgba(0,0,0,0.06)", border: "1.5px solid #e8e5e0" }}
        >
          <div className="text-[10px] font-bold uppercase tracking-widest text-[#9b9896]">Viewing as</div>
          <div className="text-sm font-bold text-[#c8a84b] uppercase tracking-wide">{institution}</div>
        </div>
      </div>

      {/* Why flagged */}
      <div 
        className="rounded-2xl p-6 border border-[#f0b0b0]"
        style={{ background: "#fdeaea", boxShadow: "0 2px 12px rgba(0,0,0,0.06), 0 1px 3px rgba(0,0,0,0.04)" }}
      >
        <div className="text-[10px] font-bold uppercase tracking-widest text-[#b03a3a] opacity-80 mb-3">Why it was flagged</div>
        <p className="text-sm font-bold leading-relaxed text-[#b03a3a]">
          {data.evidence_text || "See evidence subgraph below."}
        </p>
      </div>

      {/* Accounts + Draft SAR */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Evidence nodes */}
        <Card className="flex flex-col max-h-[420px]">
          <SectionLabel>Evidence Graph Nodes ({data.accounts.length})</SectionLabel>
          <div className="flex-1 min-h-0 overflow-y-auto space-y-2 pr-1">
            {data.accounts.map((a, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between rounded-xl px-4 py-3 transition-colors"
                style={{ background: "#f8f7f4", border: "1px solid #eeebe5" }}
              >
                <span className="font-mono text-sm">
                  {a.account_id ? (
                    <span className="font-bold text-[#3cb371]">{a.account_id}</span>
                  ) : (
                    <span className="text-[#9b9896]">{a.hash.slice(0, 16)}…</span>
                  )}
                </span>
                <span className="text-xs font-medium text-[#9b9896]">
                  {a.institution ?? "unidentified"}
                  {a.account_id ? " · your account" : " · pseudonymised"}
                </span>
              </div>
            ))}
          </div>
        </Card>

        {/* Draft SAR */}
        <Card className="flex flex-col max-h-[420px]">
          <div className="flex items-center justify-between mb-3">
            <SectionLabel>Draft SAR Report</SectionLabel>
            <div className="flex gap-2">
              <button 
                onClick={downloadSAR}
                className="rounded-full px-3 py-1 text-[10px] font-bold uppercase tracking-widest transition-colors hover:bg-[#e8e5e0]"
                style={{ background: "#f8f7f4", color: "#6b6b70", border: "1px solid #e8e5e0" }}
              >
                Download .txt
              </button>
              <span
                className="rounded-full px-3 py-1 text-[10px] font-bold uppercase tracking-widest"
                style={{ background: "#fdf6e3", color: "#8a7030", border: "1px solid #e9d98a" }}
              >
                Requires human review
              </span>
            </div>
          </div>
          <textarea
            value={narrative}
            onChange={(e) => setNarrative(e.target.value)}
            rows={10}
            className="flex-1 w-full rounded-xl p-4 font-mono text-sm leading-relaxed text-[#3a3a3e] focus:outline-none resize-none transition-all"
            style={{
              background: "#f8f7f4",
              border: "1.5px solid #e8e5e0",
            }}
            onFocus={(e) => { e.currentTarget.style.border = "1.5px solid #c8a84b"; e.currentTarget.style.boxShadow = "0 0 0 3px rgba(200,168,75,0.12)"; }}
            onBlur={(e) => { e.currentTarget.style.border = "1.5px solid #e8e5e0"; e.currentTarget.style.boxShadow = "none"; }}
          />
          <p className="mt-2 text-xs text-[#9b9896]">
            Machine-generated draft ({data.draft_str?.source}). Verify facts and add KYC context before any filing decision.
          </p>
        </Card>
      </div>

      {/* Network Topology */}
      {data.topology && data.topology.nodes.length > 0 && (
        <Card>
          <SectionLabel>Network Topology</SectionLabel>
          <div
            ref={containerRef}
            className="w-full h-[380px] rounded-xl overflow-hidden"
            style={{ background: "#1c1c1e" }}
          >
            <ForceGraph2D
              width={graphDim.width}
              height={graphDim.height}
              graphData={{
                nodes: data.topology.nodes.map((n) => ({ ...n })),
                links: data.topology.edges.map((e) => ({ ...e })),
              }}
              nodeId="id"
              nodeLabel={(n: any) =>
                n.group === institution
                  ? `Your Account: ${n.id}`
                  : `External: ${n.id.substring(0, 8)}...`
              }
              nodeColor={(n: any) => (n.group === institution ? "#c8a84b" : "#4b5563")}
              linkColor={() => "#2e2e32"}
              backgroundColor="#1c1c1e"
            />
          </div>
        </Card>
      )}

      {/* Decision panel */}
      <Card>
        <SectionLabel>Record Decision</SectionLabel>
        <div className="flex flex-wrap items-center gap-3">
          <input
            value={officer}
            onChange={(e) => setOfficer(e.target.value)}
            placeholder="Reviewing officer name"
            className="rounded-xl px-4 py-2.5 text-sm text-[#1c1c1e] focus:outline-none transition-all"
            style={{ background: "#f8f7f4", border: "1.5px solid #e8e5e0", minWidth: "200px" }}
            onFocus={(e) => { e.currentTarget.style.border = "1.5px solid #c8a84b"; }}
            onBlur={(e) => { e.currentTarget.style.border = "1.5px solid #e8e5e0"; }}
          />
          {DECISIONS.map((d) => (
            <button
              key={d.key}
              id={`decision-${d.key}`}
              onClick={() => onDecide(d.key)}
              className="rounded-xl px-5 py-2.5 text-sm font-bold uppercase tracking-wider transition-all hover:opacity-85 hover:scale-[1.02]"
              style={d.style}
            >
              {d.label}
            </button>
          ))}
          {msg && (
            <span
              className="text-xs font-semibold"
              style={{ color: msgType === "success" ? "#3cb371" : "#e05252" }}
            >
              {msg}
            </span>
          )}
        </div>
      </Card>
    </div>
  );
}
