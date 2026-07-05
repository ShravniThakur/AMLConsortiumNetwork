"""Draft a Suspicious Transaction Report (STR) narrative from a case.

The draft is a **starting point for a human**, never a filing: ``draft`` always returns
``requires_human_review=True`` and ``filed=False``. A deterministic template renders the facts of
the case (pattern, involved accounts, why it was flagged); an optional local LLM (Ollama) can turn
that into fluent regulator-style prose, but the template is the source of truth and works with no
model available (so this is testable offline).

Only the **filing institution's own** accounts appear as real ids (from the owner-side resolution);
every other party's account stays a hash — the report a bank files never exposes another bank's
customer.
"""

from __future__ import annotations

_PATTERN_PHRASING = {
    "sliding_window": "funds were received and moved out again within a short window",
    "path_tracker": "funds moved through a multi-hop chain spanning several institutions",
    "round_trip": "funds left an account and returned to it through intermediaries",
    "flow_conservation": "an account forwarded almost exactly what it received (pass-through)",
    "coordinated_new_accounts": "a cluster of newly-seen accounts moved funds in concert",
}


def _account_line(a: dict) -> str:
    """One evidence-account line: real id for an owned account, hash otherwise."""
    if a.get("account_id"):
        return (
            f"- account {a['account_id']} ({a['institution']}) — owned by the reporting institution"
        )
    inst = a.get("institution") or "an unidentified institution"
    return f"- account {a['hash'][:12]}… ({inst}) — pseudonymised, owned by another institution"


def render_template(case_view: dict) -> str:
    """Deterministic STR narrative from a resolved case view (no LLM)."""
    inst = case_view.get("viewing_institution", "the reporting institution")
    pattern = case_view.get("pattern", "unknown")
    desc = _PATTERN_PHRASING.get(pattern, pattern.replace("_", " "))
    accounts = case_view.get("accounts", [])
    lines = "\n".join(_account_line(a) for a in accounts)
    parties = ", ".join(case_view.get("institutions", [])) or inst

    return (
        f"DRAFT SUSPICIOUS TRANSACTION REPORT — for review by the Principal Officer\n"
        f"Reporting institution: {inst}\n"
        f"Alert reference: {case_view.get('alert_id', '')}\n\n"
        f"Summary: automated cross-institution monitoring flagged a suspected layering pattern "
        f"({pattern.replace('_', ' ')}, model score {float(case_view.get('score', 0.0)):.2f}) in "
        f"which {desc}. The activity spans: {parties}.\n\n"
        f"Accounts in the evidence subgraph:\n{lines}\n\n"
        f"Basis for suspicion: "
        f"{case_view.get('evidence_text') or 'see attached evidence subgraph.'}\n\n"
        f"This is a machine-generated DRAFT. A compliance officer must verify the facts, add "
        f"KYC/context, and decide whether to file. No report is submitted automatically."
    )


def draft(
    case_view: dict,
    *,
    use_llm: bool = False,
    host: str | None = None,
    model: str = "llama3.1:8b",
    timeout: float = 120.0,
) -> dict:
    """Return a draft STR: ``{narrative, requires_human_review, filed, source}``.

    ``use_llm`` sends the template to a local Ollama model to produce fluent prose; on any failure
    it falls back to the template. Filing is never automated regardless.
    """
    template = render_template(case_view)
    narrative, source = template, "template"

    if use_llm:
        try:
            narrative = _llm_polish(template, host=host, model=model, timeout=timeout)
            source = f"llm:{model}"
        except Exception:  # noqa: BLE001 — never let LLM issues block the draft; template is truth
            narrative, source = template, "template"

    return {
        "alert_id": case_view.get("alert_id"),
        "institution": case_view.get("viewing_institution"),
        "narrative": narrative,
        "source": source,
        "requires_human_review": True,
        "filed": False,
    }


def _llm_polish(template: str, *, host: str | None, model: str, timeout: float) -> str:
    """Ask a local Ollama model to rewrite the template as a formal STR narrative."""
    import os

    import httpx

    host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    prompt = (
        "You are assisting a bank compliance officer. Rewrite the following DRAFT suspicious "
        "transaction report as a clear, formal narrative. Use ONLY the facts given — invent "
        "nothing, add no account numbers or amounts not present. Keep it concise.\n\n" + template
    )
    resp = httpx.post(
        f"{host}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()
