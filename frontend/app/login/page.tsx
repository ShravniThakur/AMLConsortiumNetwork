"use client";

import { INSTITUTIONS } from "@/lib/api";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export default function Login() {
  const router = useRouter();
  const [selectedInst, setSelectedInst] = useState(INSTITUTIONS[0]);

  useEffect(() => {
    // If already logged in, redirect to dashboard
    if (localStorage.getItem("acn_institution")) {
      router.push("/");
    }
  }, [router]);

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    localStorage.setItem("acn_institution", selectedInst);
    window.location.href = "/";
  };

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden py-12">
      {/* Background glow effects and waves */}
      <div className="fixed inset-0 z-0 overflow-hidden pointer-events-none">
        <div className="absolute inset-0 bg-[url('/bg-waves.png')] bg-cover bg-center opacity-40 mix-blend-screen" />
        <div className="absolute top-1/4 left-1/4 h-96 w-96 rounded-full bg-mint/10 blur-[120px]" />
        <div className="absolute bottom-1/4 right-1/4 h-96 w-96 rounded-full bg-gold/10 blur-[120px]" />
      </div>

      <div className="z-10 text-center space-y-6 max-w-4xl px-4 mt-8">
        <h1 className="text-4xl md:text-6xl font-bold tracking-tight text-white uppercase" style={{ letterSpacing: '0.1em' }}>
          The Power of
          <br />
          <span className="text-gold">Collaborative Compliance</span>
        </h1>
        <p className="text-xl md:text-2xl text-gray-300">
          Join the network. Reduce risk.
        </p>

        <form onSubmit={handleLogin} className="mx-auto mt-12 max-w-sm space-y-4 rounded-2xl border border-midnight-border bg-midnight-card/80 p-8 shadow-2xl backdrop-blur-sm">
          <div>
            <label className="mb-2 block text-sm font-medium text-gray-400 text-left">
              Select Institution
            </label>
            <select
              value={selectedInst}
              onChange={(e) => setSelectedInst(e.target.value)}
              className="w-full rounded-lg border border-midnight-border bg-midnight px-4 py-3 text-white focus:border-mint focus:outline-none focus:ring-1 focus:ring-mint"
            >
              {INSTITUTIONS.map((inst) => (
                <option key={inst} value={inst}>
                  {inst}
                </option>
              ))}
            </select>
          </div>
          
          <button
            type="submit"
            className="w-full rounded-full bg-mint px-6 py-3 text-sm font-bold uppercase tracking-wider text-midnight-card transition-all hover:bg-mint-hover hover:scale-[1.02] focus:outline-none focus:ring-2 focus:ring-mint focus:ring-offset-2 focus:ring-offset-midnight"
          >
            Join The Network
          </button>
        </form>

        <div className="mt-16 grid grid-cols-1 md:grid-cols-4 gap-6">
          <FeatureCard 
            title="COLLECTIVE INTELLIGENCE" 
            desc="Federated graph analytics across boundaries."
            icon="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9"
          />
          <FeatureCard 
            title="SHARED ALERTS" 
            desc="Detect complex layering invisible to one bank."
            icon="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
          />
          <FeatureCard 
            title="REGULATORY FORUMS" 
            desc="Standardized, compliance-ready narrative generation."
            icon="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"
          />
          <FeatureCard 
            title="COOPERATIVE REPORTING" 
            desc="Secure STR drafting without raw data sharing."
            icon="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          />
        </div>
      </div>
    </div>
  );
}

function FeatureCard({ title, desc, icon }: { title: string, desc: string, icon: string }) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-midnight-border bg-midnight-card/60 p-6 text-center backdrop-blur transition-all hover:border-gold/50">
      <svg className="mb-4 h-10 w-10 text-mint" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={icon} />
      </svg>
      <h3 className="mb-2 text-sm font-bold text-white tracking-wider">{title}</h3>
      <p className="text-xs text-gray-400">{desc}</p>
    </div>
  );
}

