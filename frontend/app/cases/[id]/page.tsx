"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CaseDetail, decide, getCase, INSTITUTIONS } from "../../../lib/api";
import dynamic from "next/dynamic";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

const DECISIONS = [
  { key: "file", label: "File STR", cls: "bg-mint hover:bg-mint-hover text-gray-400 shadow-lg shadow-mint/20 border-mint" },
  { key: "escalate", label: "Escalate", cls: "bg-gold hover:bg-gold-hover text-gray-400 shadow-lg shadow-gold/20 border-gold" },
  { key: "dismiss", label: "Dismiss", cls: "bg-midnight-card hover:bg-midnight-border text-gray-400 border-midnight-border" },
];

export default function CasePage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const [institution, setInstitution] = useState<string>("");
  const [data, setData] = useState<CaseDetail | null>(null);
  const [narrative, setNarrative] = useState("");
  const [officer, setOfficer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

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
    if (!inst) {
      router.push("/login");
      return;
    }
    setInstitution(inst);
  }, [router]);

  useEffect(() => {
    if (institution) {
      load();
    }
  }, [load, institution]);

  async function onDecide(decision: string) {
    if (!officer.trim()) {
      setMsg("Enter the reviewing officer's name first.");
      return;
    }
    try {
      await decide(params.id, decision, officer.trim());
      setMsg(`Recorded: ${decision}.`);
      load();
    } catch (e) {
      setMsg(`Failed: ${e}`);
    }
  }

  if (error)
    return (
      <div className="rounded border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
        {error}. <Link href="/" className="underline">Back to queue</Link>
      </div>
    );
  if (!data) return <p className="text-sm text-slate-500">Loading…</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Link href="/" className="text-sm text-sky-300 hover:underline">
            ← Alert queue
          </Link>
          <h1 className="mt-1 text-3xl font-bold tracking-wider uppercase text-white">
            {data.pattern.replace(/_/g, " ")}
          </h1>
          <p className="mt-2 text-sm text-gray-400 font-medium">
            Model score <span className="tabular-nums text-gold font-bold">{data.score?.toFixed(2)}</span>{" "}
            · status <span className="text-gray-200 uppercase tracking-wider">{data.status}</span> · involves{" "}
            {data.institutions.join(", ")}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <label className="text-xs text-gray-400 font-bold uppercase tracking-wider">Viewing as</label>
          <span className="rounded-lg border border-gold/40 bg-gold/5 px-4 py-2 text-sm font-bold uppercase tracking-wider text-gold shadow-lg">
            {institution}
          </span>
        </div>
      </div>

      <section className="rounded-2xl border-2 border-mint-dark bg-mint p-6 shadow-xl">
        <h2 className="mb-2 text-base font-black uppercase tracking-wider text-midnight/70">Why it was flagged</h2>
        <p className="text-base leading-relaxed text-midnight font-medium">
          {data.evidence_text || "See evidence subgraph."}
        </p>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">
        <section className="rounded-2xl border border-midnight-border bg-midnight-card/80 p-6 shadow-xl flex flex-col h-full max-h-[450px]">
          <h2 className="mb-4 text-base font-bold uppercase tracking-wider text-white flex-shrink-0">
            Evidence graph nodes ({data.accounts.length})
          </h2>
          <div className="flex-1 min-h-0 overflow-y-auto pr-2 custom-scrollbar">
            <ul className="space-y-2">
              {data.accounts.map((a, idx) => (
                <li
                  key={idx}
                  className="flex items-center justify-between rounded-lg border border-midnight-border bg-midnight px-4 py-3 hover:border-gold/30 transition-colors"
                >
                  <span className="font-mono text-base">
                    {a.account_id ? (
                      <span className="text-mint font-bold">{a.account_id}</span>
                    ) : (
                      <span className="text-gray-400">{a.hash.slice(0, 16)}…</span>
                    )}
                  </span>
                  <span className="text-sm font-medium uppercase tracking-wider text-gray-400">
                    {a.institution ?? "unidentified"}
                    {a.account_id ? " · your account" : " · pseudonymised"}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="rounded-2xl border border-midnight-border bg-midnight-card/80 p-6 shadow-xl relative overflow-hidden flex flex-col h-full max-h-[450px]">
          {/* Subtle mint glow in corner of draft area */}
          <div className="absolute top-0 right-0 h-32 w-32 rounded-full bg-mint/5 blur-3xl pointer-events-none" />
          
          <div className="mb-4 flex items-center justify-between relative z-10 flex-shrink-0">
            <h2 className="text-base font-bold uppercase tracking-wider text-white">Draft SAR Report</h2>
            <span className="rounded-full bg-gold/10 px-3 py-1 text-sm font-bold uppercase tracking-wider text-gold border border-gold/30">
              requires human review
            </span>
          </div>
          <textarea
            value={narrative}
            onChange={(e) => setNarrative(e.target.value)}
            rows={10}
            className="flex-1 relative z-10 w-full rounded-xl border border-midnight-border bg-midnight p-4 font-mono text-base leading-relaxed text-gray-300 focus:border-mint focus:outline-none focus:ring-1 focus:ring-mint resize-y custom-scrollbar"
          />
          <p className="mt-3 text-sm text-gray-400 relative z-10 flex-shrink-0">
            Machine-generated draft ({data.draft_str?.source}). Verify facts and add KYC context
            before any filing decision.
          </p>
        </section>
      </div>

      {data.topology && data.topology.nodes.length > 0 && (
        <section className="rounded-2xl border border-midnight-border bg-midnight-card/80 p-6 shadow-xl flex flex-col">
          <h2 className="mb-4 text-base font-bold uppercase tracking-wider text-white flex-shrink-0">
            Network Topology
          </h2>
          <div className="w-full h-[400px] border border-midnight-border rounded-lg overflow-hidden bg-midnight flex items-center justify-center">
            <ForceGraph2D
              graphData={{
                nodes: data.topology.nodes.map(n => ({ ...n })),
                links: data.topology.edges.map(e => ({ ...e }))
              }}
              nodeId="id"
              nodeLabel={(n: any) => n.group === institution ? `Your Account: ${n.id}` : `External: ${n.id.substring(0,8)}...`}
              nodeColor={(n: any) => n.group === institution ? "#d4af37" : "#4b5563"}
              linkColor={() => "#2a2e3a"}
              backgroundColor="#0b0d14"
              width={1000} // ForceGraph often needs explicit bounds, we'll let it auto-size if possible but can provide fallback
            />
          </div>
        </section>
      )}

      <section className="rounded-2xl border border-midnight-border bg-midnight-card/80 p-6 shadow-xl">
        <div className="flex flex-wrap items-center gap-4">
          <input
            value={officer}
            onChange={(e) => setOfficer(e.target.value)}
            placeholder="Reviewing officer"
            className="rounded-lg border border-midnight-border bg-midnight px-4 py-2.5 text-sm text-white focus:border-mint focus:outline-none focus:ring-1 focus:ring-mint"
          />
          {DECISIONS.map((d) => (
            <button
              key={d.key}
              onClick={() => onDecide(d.key)}
              className={`rounded-lg border px-6 py-2.5 text-sm font-bold uppercase tracking-wider transition-all hover:scale-[1.02] ${d.cls}`}
            >
              {d.label}
            </button>
          ))}
          {msg && <span className="text-sm text-slate-400">{msg}</span>}
        </div>
      </section>
    </div>
  );
}
