"""Assign banks to 5 non-IID institutions.

Two failure modes to avoid at once:
- pure k-means(k=5) on the real LI-Medium distribution leaves 3 of 5 institutions empty
  (a few huge-volume banks + a ~115k-bank fraud-free tail);
- naive volume-balancing makes the institutions statistically identical (KL ~ 0), so the
  institutions are IID and there is nothing to demonstrate.

So we do an **amount-stratified, volume-balanced** partition: sort banks by their
transaction-size profile (``amount_mean``) so each institution gets a *distinct* amount
range (strong non-IID — INST_A smallest-amount → INST_E largest), then cut the sorted
banks into five **contiguous bins of equal transaction volume** so every institution is
substantial and none is empty. Deterministic and reproducible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .schema import INSTITUTIONS


def per_bank_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-bank stats: profiled over sender *and* receiver
    participation, so every bank — including receiver-only ones — gets a profile."""
    send = df[["from_bank", "amount_paid", "payment_currency", "is_laundering"]].rename(
        columns={"from_bank": "bank_id"}
    )
    recv = df[["to_bank", "amount_paid", "payment_currency", "is_laundering"]].rename(
        columns={"to_bank": "bank_id"}
    )
    participation = pd.concat([send, recv], ignore_index=True)
    stats = participation.groupby("bank_id").agg(
        txn_count=("amount_paid", "size"),
        amount_mean=("amount_paid", "mean"),
        fraud_rate=("is_laundering", "mean"),
        currency_count=("payment_currency", "nunique"),
    )
    return stats.reset_index()


def assign_institutions(bank_stats: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Amount-stratified, volume-balanced partition into 5 institutions.

    Sort banks by ``amount_mean`` and walk them in order, filling institution INST_A then
    INST_B … Each institution is closed once it holds its ~1/5 share of total transaction
    volume, so the five end up with comparable volume (none empty — the earlier failure
    mode) while carrying distinct transaction-size profiles (strong non-IID). A guard
    forces closure early enough that every remaining institution still gets ≥1 bank.

    Returns ``bank_stats`` plus an ``institution`` column, sorted by ``amount_mean``.
    ``seed`` is accepted for a stable signature (the assignment is deterministic).
    """
    if len(bank_stats) < len(INSTITUTIONS):
        raise ValueError(
            f"need at least {len(INSTITUTIONS)} banks to form {len(INSTITUTIONS)} "
            f"institutions; got {len(bank_stats)}."
        )
    bs = bank_stats.sort_values("amount_mean", kind="stable").reset_index(drop=True)
    vols = bs["txn_count"].to_numpy(dtype=float)
    target = vols.sum() / len(INSTITUTIONS)

    assign = np.empty(len(bs), dtype=object)
    idx = 0
    cum = 0.0
    n = len(bs)
    for i in range(n):
        assign[i] = INSTITUTIONS[idx]
        cum += vols[i]
        if idx < len(INSTITUTIONS) - 1:
            remaining_banks_after = n - (i + 1)
            remaining_insts_after = len(INSTITUTIONS) - (idx + 1)
            reached_target = cum >= target * (idx + 1)
            must_advance = remaining_banks_after <= remaining_insts_after
            if reached_target or must_advance:
                idx += 1

    out = bs.copy()
    out["institution"] = assign
    return out


def bank_to_institution(assignment: pd.DataFrame) -> dict[int, str]:
    """Flatten the assignment table into a ``{bank_id: institution}`` map."""
    return dict(zip(assignment["bank_id"], assignment["institution"], strict=True))
