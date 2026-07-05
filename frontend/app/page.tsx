"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CaseSummary, listCases } from "../lib/api";

const PATTERN_LABEL: Record<string, string> = {
  sliding_window: "Rapid in/out",
  path_tracker: "Cross-bank chain",
  round_trip: "Round-trip",
  flow_conservation: "Pass-through mule",
  coordinated_new_accounts: "Coordinated new accounts",
};

const STATUSES = ["open", "escalated", "filed", "dismissed"];

function StatusBadge({ status }: { status: string }) {
  const c: Record<string, string> = {
    open: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    escalated: "bg-purple-500/15 text-purple-300 border-purple-500/30",
    filed: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    dismissed: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  };
  return (
    <span className={`rounded border px-2 py-0.5 text-xs font-medium ${c[status] ?? c.open}`}>
      {status}
    </span>
  );
}

export default function Dashboard() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    listCases(status || undefined)
      .then((c) => {
        setCases(c);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [status]);

  return (
    <div>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white">Alert queue</h1>
          <p className="mt-1 text-sm text-slate-400">
            Cross-institution laundering alerts, worst score first. Only involved institutions see
            a case.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-500">Status</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-200"
          >
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="rounded border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          Could not reach the API ({error}). Is the service running on{" "}
          <code>localhost:8000</code>?
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : cases.length === 0 && !error ? (
        <p className="text-sm text-slate-500">No cases.</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/60 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Pattern</th>
                <th className="px-4 py-3 font-medium">Score</th>
                <th className="px-4 py-3 font-medium">Institutions</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Alert</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {cases.map((c) => (
                <tr key={c.alert_id} className="hover:bg-slate-900/40">
                  <td className="px-4 py-3">
                    <Link href={`/cases/${c.alert_id}`} className="font-medium text-sky-300 hover:underline">
                      {PATTERN_LABEL[c.pattern] ?? c.pattern}
                    </Link>
                  </td>
                  <td className="px-4 py-3 tabular-nums text-slate-300">{c.score?.toFixed(2)}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {c.institutions.map((i) => (
                        <span key={i} className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-300">
                          {i}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">
                    {c.alert_id.slice(0, 12)}…
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
