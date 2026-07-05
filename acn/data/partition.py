"""Partition the sample into five institution files + the ownership column.

Each institution's file holds the transactions it **sends** (from-bank in that cluster).
Every row also carries ``dst_institution`` — the owning institution of the destination
account, derived from the To-Bank column through the cluster assignment. This is the
hook used for ownership-based hashing: an account is hashed with its
*owning* institution's id, never the publisher's — so no cross-institution lookup is
needed at pseudonymisation time.
"""

from __future__ import annotations

import pandas as pd

from .schema import INSTITUTIONS


def add_institution_columns(df: pd.DataFrame, bank_to_inst: dict[int, str]) -> pd.DataFrame:
    """Add ``src_institution`` (from-bank owner) and ``dst_institution`` (to-bank owner)."""
    out = df.copy()
    out["src_institution"] = out["from_bank"].map(bank_to_inst)
    out["dst_institution"] = out["to_bank"].map(bank_to_inst)
    missing = out["src_institution"].isna().sum() + out["dst_institution"].isna().sum()
    if missing:
        raise ValueError(
            f"{missing} rows have no institution mapping — every bank must be clustered "
            "(check per_bank_stats covers receiver-only banks)."
        )
    return out


def partition(df: pd.DataFrame, bank_to_inst: dict[int, str]) -> dict[str, pd.DataFrame]:
    """Split into ``{INST_X: rows this institution sends}``, each carrying dst_institution.

    Returns a dict keyed by all five institutions (an institution with no sent rows maps
    to an empty frame, so downstream code can rely on all five keys existing).
    """
    enriched = add_institution_columns(df, bank_to_inst)
    return {
        inst: enriched[enriched["src_institution"] == inst].reset_index(drop=True)
        for inst in INSTITUTIONS
    }
