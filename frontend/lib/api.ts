// Client for the ACN case-management API. Base URL is build-time configurable; defaults to the
// local FastAPI service.
const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export const INSTITUTIONS = ["INST_A", "INST_B", "INST_C", "INST_D", "INST_E"];

export type CaseSummary = {
  alert_id: string;
  pattern: string;
  score: number;
  status: string;
  created_ts: number;
  institutions: string[];
};

export type Account = {
  hash: string;
  institution: string | null;
  account_id?: string | null;
};

export type DraftStr = {
  narrative: string;
  requires_human_review: boolean;
  filed: boolean;
  source: string;
};

export type CaseDetail = {
  alert_id: string;
  pattern: string;
  score: number;
  institutions: string[];
  created_ts: number;
  evidence_text: string | null;
  accounts: Account[];
  status: string;
  viewing_institution?: string;
  draft_str?: DraftStr;
};

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export async function listCases(status?: string): Promise<CaseSummary[]> {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  const data = await json<{ cases: CaseSummary[] }>(await fetch(`${BASE}/cases${q}`, { cache: "no-store" }));
  return data.cases;
}

export async function getCase(id: string, institution?: string, draft = false): Promise<CaseDetail> {
  const params = new URLSearchParams();
  if (institution) params.set("institution", institution);
  if (draft) params.set("draft", "true");
  const q = params.toString() ? `?${params.toString()}` : "";
  return json<CaseDetail>(await fetch(`${BASE}/cases/${id}${q}`, { cache: "no-store" }));
}

export async function decide(id: string, decision: string, officer: string) {
  return json(
    await fetch(`${BASE}/cases/${id}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, officer }),
    }),
  );
}
