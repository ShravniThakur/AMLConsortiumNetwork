"use client";

import Link from "next/link";
import { useEffect, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { CaseSummary, listCases } from "../lib/api";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
} from "recharts";

// ─── Constants ────────────────────────────────────────────────────────────────

const PATTERN_LABEL: Record<string, string> = {
  sliding_window: "Rapid In/Out",
  path_tracker: "Cross-Bank Chain",
  round_trip: "Round-Trip",
  flow_conservation: "Pass-Through Mule",
  coordinated_new_accounts: "Coordinated New Accs",
};

const STATUSES = ["open", "escalated", "filed", "dismissed"];

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    open: "badge-open",
    escalated: "badge-escalated",
    filed: "badge-filed",
    dismissed: "badge-dismissed",
  };
  return <span className={`badge ${cls[status] ?? "badge-open"}`}>{status}</span>;
}

// Zarss-style colored KPI cards
const CARD_THEMES = {
  olive: {
    bg: "#c5d4aa",
    labelColor: "rgba(30,50,10,0.60)",
    valueColor: "#1e3a0a",
    subColor: "rgba(30,50,10,0.55)",
    iconBg: "rgba(30,50,10,0.12)",
    iconColor: "#2e5210",
    wave: "#a8bf88",
  },
  gold: {
    bg: "#e8d080",
    labelColor: "rgba(80,55,0,0.60)",
    valueColor: "#3a2800",
    subColor: "rgba(80,55,0,0.55)",
    iconBg: "rgba(80,55,0,0.12)",
    iconColor: "#5a3e00",
    wave: "#d4b860",
  },
  periwinkle: {
    bg: "#c0c6f0",
    labelColor: "rgba(20,20,90,0.55)",
    valueColor: "#1a1a6a",
    subColor: "rgba(20,20,90,0.50)",
    iconBg: "rgba(20,20,90,0.10)",
    iconColor: "#2a2a8a",
    wave: "#9aa0e0",
  },
  danger: {
    bg: "#f0c8c8",
    labelColor: "rgba(90,10,10,0.55)",
    valueColor: "#5a0a0a",
    subColor: "rgba(90,10,10,0.50)",
    iconBg: "rgba(90,10,10,0.10)",
    iconColor: "#8a1a1a",
    wave: "#e0a0a0",
  },
};

function KpiCard({
  label,
  value,
  sub,
  accent,
  icon,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: "olive" | "periwinkle" | "gold" | "danger";
  icon: React.ReactNode;
}) {
  const t = CARD_THEMES[accent ?? "gold"];
  return (
    <div
      className="card-lift rounded-2xl overflow-hidden flex flex-col"
      style={{ background: t.bg, boxShadow: "0 2px 14px rgba(0,0,0,0.10)" }}
    >
      <div className="px-5 pt-5 pb-3 flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: t.labelColor }}>{label}</div>
          <div className="text-3xl font-black leading-none mb-1" style={{ color: t.valueColor }}>{value}</div>
          {sub && <div className="text-[11px] font-semibold" style={{ color: t.subColor }}>{sub}</div>}
        </div>
        <div
          className="flex h-10 w-10 items-center justify-center rounded-xl flex-shrink-0 ml-3 mt-0.5"
          style={{ background: t.iconBg, color: t.iconColor }}
        >
          {icon}
        </div>
      </div>
      {/* Mini wave sparkline decoration */}
      <div className="px-5 pb-4 mt-auto">
        <svg viewBox="0 0 120 28" height="28" width="100%" preserveAspectRatio="none">
          <polyline
            points="0,20 15,12 30,16 45,8 60,14 75,6 90,12 105,8 120,14"
            fill="none"
            stroke={t.wave}
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
    </div>
  );
}

function SectionHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-4">
      <h2 className="text-base font-bold uppercase tracking-wider text-[#1c1c1e]">{title}</h2>
      {action}
    </div>
  );
}

// ─── Right Panel: Recent Alert Feed ──────────────────────────────────────────


// ─── Main Dashboard ───────────────────────────────────────────────────────────



export default function Dashboard() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [institution, setInstitution] = useState<string>("");
  const [search, setSearch] = useState<string>("");
  const router = useRouter();

  useEffect(() => {
    const inst = localStorage.getItem("acn_institution");
    if (!inst) { router.push("/login"); return; }
    setInstitution(inst);
  }, [router]);

  useEffect(() => {
    if (!institution) return;
    setLoading(true);
    listCases(status || undefined, institution)
      .then((c) => { setCases(c); setError(null); })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [status, institution]);

  const total = cases.length;
  const openCount     = cases.filter((c) => c.status === "open").length;
  const escCount      = cases.filter((c) => c.status === "escalated").length;
  const filedCount    = cases.filter((c) => c.status === "filed").length;
  const avgScore      = (cases.reduce((s, c) => s + (c.score || 0), 0) / Math.max(total, 1)).toFixed(2);

  // Top pattern
  const topPattern = useMemo(() => {
    if (!cases.length) return null;
    const counts = cases.reduce((acc, c) => { acc[c.pattern] = (acc[c.pattern] || 0) + 1; return acc; }, {} as Record<string, number>);
    const [key, cnt] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
    return { label: PATTERN_LABEL[key] ?? key, count: cnt };
  }, [cases]);

  // Charts
  const chartData = useMemo(() => {
    // Timeline
    const tMap = cases.reduce((acc, c) => {
      const d = new Date(c.created_ts * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" });
      acc[d] = (acc[d] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);
    const timeline = Object.entries(tMap).map(([date, alerts]) => ({ date, alerts }));

    // Score buckets
    const sBuckets = [
      { range: "0–20",   min: 0,   max: 0.2, count: 0 },
      { range: "20–40",  min: 0.2, max: 0.4, count: 0 },
      { range: "40–60",  min: 0.4, max: 0.6, count: 0 },
      { range: "60–80",  min: 0.6, max: 0.8, count: 0 },
      { range: "80–100", min: 0.8, max: 1.0, count: 0 },
    ];
    cases.forEach((c) => {
      const s = c.score || 0;
      const b = sBuckets.find((b) => s >= b.min && (s < b.max || (b.max === 1.0 && s <= 1.0)));
      if (b) b.count += 1;
    });

    // Pattern bars
    const patterns = Object.keys(PATTERN_LABEL).map((key) => ({
      name: PATTERN_LABEL[key],
      alerts: cases.filter((c) => c.pattern === key).length,
    })).filter((d) => d.alerts > 0);

    return { timeline, sBuckets, patterns };
  }, [cases]);

  // Filtered cases for table
  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return cases.filter((c) =>
      !q ||
      (PATTERN_LABEL[c.pattern] ?? c.pattern).toLowerCase().includes(q) ||
      c.institutions.some((i) => i.toLowerCase().includes(q)) ||
      c.status.includes(q)
    );
  }, [cases, search]);

  if (!institution) return null;

  return (
    <main className="px-7 py-7 fade-in-up">


          {/* Top bar */}
          <div className="mb-6">
            <h1 className="text-2xl font-black text-[#1c1c1e] tracking-tight">Dashboard</h1>
            <p className="text-sm text-[#6b6b70] font-medium mt-0.5">AML Alert Queue · Unified Compliance View</p>
          </div>


          {/* KPI cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6 stagger-children">
            <KpiCard
              label="Network Alerts"
              value={total}
              sub={`${openCount} open`}
              accent="olive"
              icon={
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                  <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                </svg>
              }
            />
            <KpiCard
              label="Escalated"
              value={escCount}
              sub="require action"
              accent="danger"
              icon={
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                  <line x1="12" y1="9" x2="12" y2="13" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
              }
            />
            <KpiCard
              label="Avg Risk Score"
              value={avgScore}
              sub={parseFloat(avgScore) > 0.7 ? "⚠ High risk" : "Moderate"}
              accent="gold"
              icon={
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
                </svg>
              }
            />
            <KpiCard
              label="Top Typology"
              value={topPattern?.label ?? "—"}
              sub={topPattern ? `${topPattern.count} alerts` : ""}
              accent="periwinkle"
              icon={
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="5"  r="2" />
                  <circle cx="5"  cy="19" r="2" />
                  <circle cx="19" cy="19" r="2" />
                  <line x1="12" y1="7" x2="5" y2="17" />
                  <line x1="12" y1="7" x2="19" y2="17" />
                </svg>
              }
            />
          </div>

          {/* Analytics Charts */}
          {cases.length > 0 && (
            <div id="analytics" className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6" style={{ scrollMarginTop: "20px" }}>
              {/* Alert Volume Timeline */}
              <div
                className="rounded-2xl p-5"
                style={{ background: "#fff", boxShadow: "0 2px 12px rgba(0,0,0,0.06)" }}
              >
                <SectionHeader title="Alert Volume" />
                <div className="h-[180px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData.timeline} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
                      <defs>
                        <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%"  stopColor="#c8a84b" stopOpacity={0.25} />
                          <stop offset="95%" stopColor="#c8a84b" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#eeebe5" vertical={false} />
                      <XAxis dataKey="date" stroke="#555555" fontSize={13} tickLine={false} axisLine={false} tickMargin={8} />
                      <YAxis stroke="#555555" fontSize={13} tickLine={false} axisLine={false} />
                      <RechartsTooltip
                        contentStyle={{ background: "#fff", border: "1px solid #e8e5e0", borderRadius: "10px", fontSize: "12px", boxShadow: "0 4px 16px rgba(0,0,0,0.08)" }}
                        itemStyle={{ color: "#c8a84b", fontWeight: "700" }}
                        labelStyle={{ color: "#6b6b70", fontWeight: "600" }}
                      />
                      <Area type="monotone" dataKey="alerts" stroke="#c8a84b" strokeWidth={2.5} fillOpacity={1} fill="url(#areaGrad)" dot={{ fill: "#c8a84b", r: 3, strokeWidth: 0 }} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Score Distribution */}
              <div
                className="rounded-2xl p-5"
                style={{ background: "#fff", boxShadow: "0 2px 12px rgba(0,0,0,0.06)" }}
              >
                <SectionHeader title="Score Distribution" />
                <div className="h-[180px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData.sBuckets} margin={{ top: 5, right: 5, left: -30, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#eeebe5" vertical={false} />
                      <XAxis dataKey="range" stroke="#555555" fontSize={13} tickLine={false} axisLine={false} tickMargin={8} />
                      <YAxis stroke="#555555" fontSize={13} tickLine={false} axisLine={false} />
                      <RechartsTooltip
                        contentStyle={{ background: "#fff", border: "1px solid #e8e5e0", borderRadius: "10px", fontSize: "12px", boxShadow: "0 4px 16px rgba(0,0,0,0.08)" }}
                        cursor={{ fill: "rgba(200,168,75,0.08)" }}
                      />
                      <Bar dataKey="count" name="Alerts" radius={[6, 6, 0, 0]} barSize={28}>
                        {chartData.sBuckets.map((entry, i) => (
                          <Cell key={i} fill={entry.min >= 0.8 ? "#e05252" : entry.min >= 0.6 ? "#c8a84b" : "#3cb371"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Typology Exposure */}
              {chartData.patterns.length > 0 && (
                <div
                  className="rounded-2xl p-5 lg:col-span-2"
                  style={{ background: "#fff", boxShadow: "0 2px 12px rgba(0,0,0,0.06)" }}
                >
                  <SectionHeader title="Typology Exposure" />
                  <div className="h-[160px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart layout="vertical" data={chartData.patterns} margin={{ top: 5, right: 20, left: 10, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#eeebe5" horizontal={false} />
                        <XAxis type="number" stroke="#555555" fontSize={13} tickLine={false} axisLine={false} />
                        <YAxis dataKey="name" type="category" stroke="#555555" fontSize={13} tickLine={false} axisLine={false} width={160} />
                        <RechartsTooltip
                          contentStyle={{ background: "#fff", border: "1px solid #e8e5e0", borderRadius: "10px", fontSize: "12px", boxShadow: "0 4px 16px rgba(0,0,0,0.08)" }}
                          cursor={{ fill: "rgba(200,168,75,0.08)" }}
                        />
                        <Bar dataKey="alerts" name="Alerts" fill="#7b82d4" radius={[0, 6, 6, 0]} barSize={20} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Alert Queue Table */}
          <div id="queue" style={{ scrollMarginTop: "20px" }}>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <h2 className="text-sm font-bold uppercase tracking-widest text-[#6b6b70]">Alert Queue</h2>
                <div className="h-4 w-px bg-[#e8e5e0]" />
                <div className="flex items-center gap-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-[#3a3a3a]">Status</label>
                  <select
                    id="status-filter"
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                    className="rounded-lg border border-[#e8e5e0] bg-white px-2.5 py-1 text-xs font-semibold text-[#1c1c1e] focus:outline-none focus:border-[#c8a84b]"
                  >
                    <option value="">All</option>
                    {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
              </div>
              <span className="text-xs text-[#9b9896] font-medium">{filtered.length} results</span>
            </div>

            {error && (
              <div className="rounded-xl border border-[#f0b0b0] bg-[#fdeaea] px-4 py-3 text-sm text-[#b03a3a] mb-4">
                Could not reach the API ({error}). Is the service running on <code>localhost:8000</code>?
              </div>
            )}

            {loading ? (
              <div className="flex items-center justify-center py-20 text-sm text-[#9b9896]">
                <svg className="animate-spin h-5 w-5 mr-2 text-[#c8a84b]" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                Loading alerts…
              </div>
            ) : filtered.length === 0 && !error ? (
              <div className="flex flex-col items-center justify-center py-20 text-[#9b9896]">
                <svg className="h-10 w-10 mb-3 text-[#d1cec9]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                </svg>
                <span className="text-sm font-medium">No cases found in the queue.</span>
              </div>
            ) : (
              <div
                className="rounded-2xl overflow-hidden"
                style={{ background: "#fff", boxShadow: "0 2px 12px rgba(0,0,0,0.06), 0 1px 3px rgba(0,0,0,0.04)" }}
              >
                <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead
                      className="sticky top-0 z-10 text-left"
                      style={{ background: "#fafaf8", borderBottom: "1px solid #eeebe5" }}
                    >
                      <tr>
                        <th className="px-5 py-3.5 text-xs font-bold uppercase tracking-wider text-[#3a3a3a]">Pattern</th>
                        <th className="px-5 py-3.5 text-xs font-bold uppercase tracking-wider text-[#3a3a3a]">Risk Score</th>
                        <th className="px-5 py-3.5 text-xs font-bold uppercase tracking-wider text-[#3a3a3a]">Institutions</th>
                        <th className="px-5 py-3.5 text-xs font-bold uppercase tracking-wider text-[#3a3a3a]">Status</th>
                        <th className="px-5 py-3.5 text-xs font-bold uppercase tracking-wider text-[#3a3a3a] text-right">Alert ID</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((c, idx) => (
                        <tr
                          key={c.alert_id}
                          className="alert-row border-b border-[#f5f3ef]"
                          style={{ animationDelay: `${idx * 0.03}s` }}
                        >
                          <td className="px-5 py-3.5 whitespace-nowrap">
                            <Link
                              href={`/cases/${c.alert_id}`}
                              className="font-semibold text-[#1c1c1e] hover:text-[#c8a84b] transition-colors text-sm"
                            >
                              {PATTERN_LABEL[c.pattern] ?? c.pattern}
                            </Link>
                          </td>
                          <td className="px-5 py-3.5 whitespace-nowrap">
                            <div className="flex items-center gap-3">
                              <span
                                className={`font-black text-sm tabular-nums ${
                                  (c.score ?? 0) >= 0.8
                                    ? "text-[#e05252]"
                                    : (c.score ?? 0) >= 0.5
                                    ? "text-[#c8a84b]"
                                    : "text-[#3cb371]"
                                }`}
                              >
                                {c.score?.toFixed(2)}
                              </span>
                              <div className="w-14 h-1.5 bg-[#f0efeb] rounded-full overflow-hidden hidden sm:block">
                                <div
                                  className="h-full rounded-full transition-all"
                                  style={{
                                    width: `${Math.min(100, (c.score || 0) * 100)}%`,
                                    background: (c.score ?? 0) >= 0.8 ? "#e05252" : (c.score ?? 0) >= 0.5 ? "#c8a84b" : "#3cb371",
                                  }}
                                />
                              </div>
                            </div>
                          </td>
                          <td className="px-5 py-3.5">
                            <div className="flex flex-wrap gap-1.5">
                              {c.institutions.map((i) => (
                                <span
                                  key={i}
                                  className="rounded-full px-2.5 py-0.5 text-[10px] font-semibold tracking-wide uppercase"
                                  style={{ background: "#f0efeb", color: "#6b6b70" }}
                                >
                                  {i}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className="px-5 py-3.5 whitespace-nowrap">
                            <StatusBadge status={c.status} />
                          </td>
                          <td className="px-5 py-3.5 whitespace-nowrap text-right font-mono text-xs text-[#b8b5af]">
                            {c.alert_id.substring(0, 8)}…
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
    </main>
  );
}
