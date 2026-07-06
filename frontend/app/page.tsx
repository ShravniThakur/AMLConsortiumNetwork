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
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";

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
    open: "bg-gold text-midnight font-bold border-none shadow-sm shadow-gold/20",
    escalated: "bg-red-500 text-white font-bold border-none shadow-sm shadow-red-500/20",
    filed: "bg-mint text-midnight font-bold border-none shadow-sm shadow-mint/20",
    dismissed: "bg-gray-700 text-gray-300 font-bold border-none",
  };
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-xs tracking-wider uppercase ${c[status] ?? c.open}`}>
      {status}
    </span>
  );
}

export default function Dashboard() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [institution, setInstitution] = useState<string>("");
  const router = useRouter();

  useEffect(() => {
    const inst = localStorage.getItem("acn_institution");
    if (!inst) {
      router.push("/login");
      return;
    }
    setInstitution(inst);
  }, [router]);

  useEffect(() => {
    if (!institution) return;
    setLoading(true);
    listCases(status || undefined, institution)
      .then((c) => {
        setCases(c);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [status, institution]);

  const total = cases.length;
  const openCount = cases.filter((c) => c.status === "open").length;
  const escCount = cases.filter((c) => c.status === "escalated").length;
  const filedCount = cases.filter((c) => c.status === "filed").length;
  const getPercentage = (count: number) => (total > 0 ? (count / total) * 100 : 0);

  const chartData = useMemo(() => {
    // Timeline
    const tData = cases.reduce((acc, c) => {
      const date = new Date(c.created_ts * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      acc[date] = (acc[date] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);
    const sortedTimeline = Object.entries(tData).map(([date, alerts]) => ({ date, alerts }));

    // Scores
    const sBuckets = [
      { range: '0-20', min: 0, max: 0.2, count: 0 },
      { range: '20-40', min: 0.2, max: 0.4, count: 0 },
      { range: '40-60', min: 0.4, max: 0.6, count: 0 },
      { range: '60-80', min: 0.6, max: 0.8, count: 0 },
      { range: '80-100', min: 0.8, max: 1.0, count: 0 },
    ];
    cases.forEach(c => {
      const s = c.score || 0;
      const b = sBuckets.find(b => s >= b.min && (s < b.max || (b.max === 1.0 && s <= 1.0)));
      if (b) b.count += 1;
    });

    // Radar & Pie Data
    const rData = Object.keys(PATTERN_LABEL).map(key => ({
      name: key, // Raw algorithm name for the pie chart legend
      subject: PATTERN_LABEL[key], // User-friendly name for the radar chart
      A: cases.filter(c => c.pattern === key).length,
      fullMark: cases.length,
    })).filter(d => d.A > 0); // Only show patterns that actually have alerts in the pie

    return { sortedTimeline, sBuckets, rData };
  }, [cases]);

  const PIE_COLORS = ['#d4af37', '#3cd070', '#8b5cf6', '#ec4899', '#3b82f6'];

  if (!institution) return null;

  return (
    <div className="flex flex-col gap-6">
      
      {/* 1. Slim Hero Banner (Solid Gold) */}
      <div className="relative overflow-hidden rounded-xl border-2 border-gold-dark bg-gold px-6 py-4 shadow-xl flex items-center justify-between">
        <div className="absolute inset-0 bg-gradient-to-r from-gold-hover via-transparent to-transparent opacity-50" />
        <div className="relative flex items-center gap-4 z-10">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-midnight/10 text-midnight shadow-inner ring-1 ring-midnight/20 flex-shrink-0">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-lg font-black tracking-tight text-midnight uppercase">Consortium Lift</h3>
              <span className="inline-flex items-center rounded-full bg-midnight px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-gold ring-1 ring-inset ring-midnight/30">
                +1.5x Detection
              </span>
            </div>
            <p className="text-xs text-midnight-card font-medium">
              Federated graph analytics boosted recall from <span className="font-bold text-midnight">37.1%</span> to <span className="font-black text-midnight">56.0%</span> at 5% FPR.
            </p>
          </div>
        </div>
        <div className="hidden md:flex gap-6 text-xs text-midnight-card">
          <div className="flex flex-col text-right">
            <span className="uppercase tracking-wider font-bold">Project</span>
            <span className="font-black text-midnight">Active</span>
          </div>
          <div className="flex flex-col text-right">
            <span className="uppercase tracking-wider font-bold">Model</span>
            <span className="font-black text-midnight">GNN v2.1</span>
          </div>
        </div>
      </div>

      {/* 2. Horizontal KPI Ribbon (Solid Mint) */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        
        {/* Total & Escalated */}
        <div className="rounded-xl border-2 border-mint-dark bg-mint p-4 shadow-lg flex items-center justify-between">
          <div>
            <h2 className="text-xs font-black uppercase tracking-wider text-midnight-card/80 mb-1">Network Alerts</h2>
            <div className="text-3xl font-black text-midnight">{cases.length}</div>
          </div>
          <div className="h-10 w-px bg-midnight/20 mx-2"></div>
          <div className="text-right">
            <h2 className="text-xs font-black uppercase tracking-wider text-midnight-card/80 mb-1">Escalated</h2>
            <div className="text-3xl font-black text-midnight">{escCount}</div>
          </div>
        </div>

        {/* Avg Risk Score */}
        <div className="rounded-xl border-2 border-mint-dark bg-mint p-4 shadow-lg relative overflow-hidden">
          <div className="absolute right-0 top-0 h-16 w-16 bg-midnight-card/20 blur-xl rounded-full" />
          <h2 className="text-xs font-black uppercase tracking-wider text-midnight-card/80 mb-1 relative z-10">Avg Risk Score</h2>
          <div className="flex items-end gap-2 relative z-10">
            <div className="text-3xl font-black text-midnight leading-none">
              {(cases.reduce((sum, c) => sum + (c.score || 0), 0) / Math.max(cases.length, 1)).toFixed(2)}
            </div>
            <span className="text-xs font-black uppercase tracking-wider text-red-600 mb-1">Critical</span>
          </div>
        </div>

        {/* Top Pattern */}
        <div className="rounded-xl border-2 border-mint-dark bg-mint p-4 shadow-lg">
          <h2 className="text-xs font-black uppercase tracking-wider text-midnight-card/80 mb-1">Top Typology</h2>
          {cases.length > 0 ? (() => {
            const patternCounts = cases.reduce((acc, c) => {
              acc[c.pattern] = (acc[c.pattern] || 0) + 1;
              return acc;
            }, {} as Record<string, number>);
            const topPattern = Object.entries(patternCounts).sort((a, b) => b[1] - a[1])[0];
            return (
              <div className="flex flex-col">
                <div className="text-base font-black text-midnight truncate uppercase tracking-wider">{PATTERN_LABEL[topPattern[0]] || topPattern[0]}</div>
                <div className="text-sm font-medium text-midnight-card/90">{topPattern[1]} alerts ({(topPattern[1]/total*100).toFixed(0)}%)</div>
              </div>
            );
          })() : <div className="text-sm text-midnight-card">None</div>}
        </div>

        {/* Queue Status Breakdown */}
        <div className="rounded-xl border-2 border-mint-dark bg-mint p-4 shadow-lg flex flex-col justify-center">
          <h2 className="text-xs font-black uppercase tracking-wider text-midnight-card/80 mb-2">Queue Health</h2>
          <div className="flex h-2 w-full rounded-full overflow-hidden mb-2 bg-midnight/20">
            <div style={{ width: `${getPercentage(openCount)}%` }} className="bg-midnight" />
            <div style={{ width: `${getPercentage(escCount)}%` }} className="bg-gold" />
            <div style={{ width: `${getPercentage(filedCount)}%` }} className="bg-midnight-card" />
          </div>
          <div className="flex justify-between text-[11px] font-black uppercase tracking-wider text-midnight-card/90">
            <span>{openCount} Open</span>
            <span className="text-midnight">{escCount} Esc</span>
            <span className="text-white">{filedCount} Filed</span>
          </div>
        </div>
      </div>

      {/* 2.5 Analytics Dashboard */}
      {cases.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          
          {/* Threat Timeline */}
          <div className="rounded-xl border border-midnight-border bg-midnight-card p-4 shadow-lg flex flex-col h-[250px]">
            <h2 className="text-sm font-bold uppercase tracking-wider text-white mb-4">Alert Volume Timeline</h2>
            <div className="flex-1 w-full min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData.sortedTimeline} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorAlerts" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#d4af37" stopOpacity={0.4}/>
                      <stop offset="95%" stopColor="#d4af37" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#4b5563" vertical={false} opacity={0.5} />
                  <XAxis dataKey="date" stroke="#e5e7eb" fontSize={12} tickLine={false} axisLine={false} tickMargin={10} />
                  <YAxis stroke="#e5e7eb" fontSize={12} tickLine={false} axisLine={false} tickMargin={10} />
                  <RechartsTooltip 
                    contentStyle={{ backgroundColor: '#1e293b', borderColor: '#e5e7eb', color: '#fff', borderRadius: '8px', fontWeight: 'bold' }}
                    itemStyle={{ color: '#d4af37' }}
                  />
                  <Area type="monotone" dataKey="alerts" stroke="#d4af37" strokeWidth={3} fillOpacity={1} fill="url(#colorAlerts)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Score Distribution */}
          <div className="rounded-xl border border-midnight-border bg-midnight-card p-4 shadow-lg flex flex-col h-[250px]">
            <h2 className="text-sm font-bold uppercase tracking-wider text-white mb-2">Score Distribution</h2>
            <div className="flex-1 w-full min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData.sBuckets} margin={{ top: 10, right: 10, left: -30, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#4b5563" vertical={false} opacity={0.5} />
                  <XAxis dataKey="range" stroke="#e5e7eb" fontSize={11} tickLine={false} axisLine={false} tickMargin={8} />
                  <YAxis stroke="#e5e7eb" fontSize={11} tickLine={false} axisLine={false} tickMargin={8} />
                  <RechartsTooltip 
                    contentStyle={{ backgroundColor: '#1e293b', borderColor: '#e5e7eb', color: '#fff', borderRadius: '8px', fontWeight: 'bold' }}
                    cursor={{fill: 'rgba(255,255,255,0.1)'}}
                  />
                  <Bar dataKey="count" fill="#3cd070" radius={[4, 4, 0, 0]} barSize={32} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Typology Exposure (Horizontal Bar) */}
          <div className="rounded-xl border border-midnight-border bg-midnight-card p-4 shadow-lg flex flex-col h-[250px] lg:col-span-2">
            <h2 className="text-sm font-bold uppercase tracking-wider text-white mb-2">Typology Exposure</h2>
            <div className="flex-1 w-full min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart layout="vertical" data={chartData.rData} margin={{ top: 10, right: 30, left: 30, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#4b5563" horizontal={false} opacity={0.5} />
                  <XAxis type="number" stroke="#e5e7eb" fontSize={11} tickLine={false} axisLine={false} />
                  <YAxis dataKey="name" type="category" stroke="#e5e7eb" fontSize={11} tickLine={false} axisLine={false} width={150} />
                  <RechartsTooltip 
                    contentStyle={{ backgroundColor: '#1e293b', borderColor: '#e5e7eb', color: '#fff', borderRadius: '8px', fontSize: '11px', fontWeight: 'bold' }}
                    cursor={{fill: 'rgba(255,255,255,0.1)'}}
                  />
                  <Bar dataKey="A" name="Alerts" fill="#d4af37" radius={[0, 4, 4, 0]} barSize={24} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

        </div>
      )}

      {/* 3. Controls & Full Width Table */}
      <div className="mt-4 flex flex-col gap-4">
        
        {/* Controls Row */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <h1 className="text-xl font-bold tracking-wider uppercase text-white">Alert queue</h1>
            <div className="h-4 w-px bg-midnight-border"></div>
            <div className="flex items-center gap-2">
              <label className="text-[10px] font-medium uppercase tracking-wider text-gray-400">Status</label>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="rounded-md border border-midnight-border bg-midnight-card px-2 py-1 text-xs font-bold uppercase tracking-wider text-gold focus:outline-none focus:border-gold"
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
          <div className="flex items-center gap-3">
            <button
              onClick={async () => {
                try {
                  await fetch('http://localhost:8000/pipeline/run', { method: 'POST' });
                  alert('Pipeline started in background!');
                } catch (e) {
                  alert('Error starting pipeline');
                }
              }}
              className="flex items-center gap-2 rounded-lg bg-mint px-4 py-2 text-xs font-bold uppercase tracking-wider text-midnight-card hover:bg-mint-hover transition-colors shadow-lg shadow-mint/20"
            >
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Run Pipeline
            </button>
            <button
              onClick={() => {
                localStorage.removeItem('acn_institution');
                router.push('/login');
              }}
              className="flex items-center gap-2 rounded-lg bg-midnight-card border border-midnight-border px-4 py-2 text-xs font-bold uppercase tracking-wider text-gray-300 hover:text-white hover:bg-midnight transition-colors"
            >
              Log Out
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            Could not reach the API ({error}). Is the service running on <code>localhost:8000</code>?
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-20 text-sm text-gray-400">Loading alerts...</div>
        ) : cases.length === 0 && !error ? (
          <div className="flex items-center justify-center py-20 text-sm text-gray-400">No cases found in the queue.</div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-midnight-border bg-midnight-card shadow-2xl">
            <div className="overflow-x-auto max-h-[800px] overflow-y-auto">
              <table className="w-full text-base">
                <thead className="bg-midnight border-b border-midnight-border text-left text-xs uppercase tracking-wider text-gray-400 font-bold sticky top-0 z-10 shadow-sm">
                  <tr>
                    <th className="px-6 py-4 whitespace-nowrap">Pattern</th>
                    <th className="px-6 py-4 whitespace-nowrap">Risk Score</th>
                    <th className="px-6 py-4">Linked Institutions</th>
                    <th className="px-6 py-4 whitespace-nowrap">Status</th>
                    <th className="px-6 py-4 whitespace-nowrap text-right">Alert ID</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-midnight-border">
                  {cases.map((c) => (
                    <tr key={c.alert_id} className="hover:bg-midnight/50 transition-colors group">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <Link href={`/cases/${c.alert_id}`} className="font-bold text-mint hover:text-mint-hover uppercase tracking-wider text-sm">
                          {PATTERN_LABEL[c.pattern] ?? c.pattern}
                        </Link>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center gap-3">
                          <span className="tabular-nums text-gold font-bold text-base">{c.score?.toFixed(2)}</span>
                          {/* Sparkline for score */}
                          <div className="w-16 h-1.5 bg-midnight-border rounded-full overflow-hidden hidden sm:block">
                            <div 
                              className="h-full bg-gold rounded-full"
                              style={{ width: `${Math.min(100, (c.score || 0) * 100)}%` }}
                            />
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex flex-wrap gap-2">
                          {c.institutions.map((i) => (
                            <span 
                              key={i} 
                              className="rounded-full bg-gray-700 px-3 py-1 text-xs font-bold uppercase tracking-wider text-gray-200 shadow-sm"
                            >
                              {i}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <StatusBadge status={c.status} />
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap font-mono text-xs text-gray-400 text-right">
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
    </div>
  );
}
