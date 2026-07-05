"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CaseDetail, decide, getCase, INSTITUTIONS } from "../../../lib/api";

const DECISIONS = [
  { key: "file", label: "File STR", cls: "bg-emerald-600 hover:bg-emerald-500" },
  { key: "escalate", label: "Escalate", cls: "bg-purple-600 hover:bg-purple-500" },
  { key: "dismiss", label: "Dismiss", cls: "bg-slate-700 hover:bg-slate-600" },
];

export default function CasePage({ params }: { params: { id: string } }) {
  const [institution, setInstitution] = useState(INSTITUTIONS[0]);
  const [data, setData] = useState<CaseDetail | null>(null);
  const [narrative, setNarrative] = useState("");
  const [officer, setOfficer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(() => {
    getCase(params.id, institution, true)
      .then((c) => {
        setData(c);
        setNarrative(c.draft_str?.narrative ?? "");
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, [params.id, institution]);

  useEffect(load, [load]);

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
          <h1 className="mt-1 text-2xl font-semibold text-white">
            {data.pattern.replace(/_/g, " ")}
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Model score <span className="tabular-nums text-slate-200">{data.score?.toFixed(2)}</span>{" "}
            · status <span className="text-slate-200">{data.status}</span> · involves{" "}
            {data.institutions.join(", ")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-500">Viewing as</label>
          <select
            value={institution}
            onChange={(e) => setInstitution(e.target.value)}
            className="rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm"
          >
            {INSTITUTIONS.map((i) => (
              <option key={i} value={i}>
                {i}
              </option>
            ))}
          </select>
        </div>
      </div>

      <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
        <h2 className="mb-1 text-sm font-semibold text-white">Why it was flagged</h2>
        <p className="text-sm leading-relaxed text-slate-300">
          {data.evidence_text || "See evidence subgraph."}
        </p>
      </section>

      <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
        <h2 className="mb-3 text-sm font-semibold text-white">
          Evidence accounts{" "}
          <span className="font-normal text-slate-500">
            — only {institution}&apos;s own accounts are resolved
          </span>
        </h2>
        <ul className="space-y-2">
          {data.accounts.map((a, idx) => (
            <li
              key={idx}
              className="flex items-center justify-between rounded border border-slate-800 px-3 py-2"
            >
              <span className="font-mono text-sm">
                {a.account_id ? (
                  <span className="text-emerald-300">{a.account_id}</span>
                ) : (
                  <span className="text-slate-400">{a.hash.slice(0, 16)}…</span>
                )}
              </span>
              <span className="text-xs text-slate-500">
                {a.institution ?? "unidentified"}
                {a.account_id ? " · your account" : " · pseudonymised"}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">Draft Suspicious Transaction Report</h2>
          <span className="rounded bg-amber-500/15 px-2 py-0.5 text-xs text-amber-300">
            requires human review · not filed
          </span>
        </div>
        <textarea
          value={narrative}
          onChange={(e) => setNarrative(e.target.value)}
          rows={14}
          className="w-full rounded border border-slate-700 bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-200"
        />
        <p className="mt-2 text-xs text-slate-500">
          Machine-generated draft ({data.draft_str?.source}). Verify facts and add KYC context
          before any filing decision.
        </p>
      </section>

      <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
        <div className="flex flex-wrap items-center gap-3">
          <input
            value={officer}
            onChange={(e) => setOfficer(e.target.value)}
            placeholder="Reviewing officer"
            className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          {DECISIONS.map((d) => (
            <button
              key={d.key}
              onClick={() => onDecide(d.key)}
              className={`rounded px-4 py-2 text-sm font-medium text-white ${d.cls}`}
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
