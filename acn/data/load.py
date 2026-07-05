"""Load + join + label the raw IBM AML LI-Medium dataset.

Raw transactions never leave the local machine beyond this pipeline — this module only
reshapes them into the canonical joined+labelled table consumed by clustering,
sampling, and partitioning. No hashing happens here; no raw
account id is ever logged (security checklist spec).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .schema import RAW_TO_CANONICAL


def find_raw_files(raw_dir: str | Path) -> tuple[Path, Path]:
    """Locate the transactions + accounts CSVs in ``raw_dir``.

    Tolerant of dataset-variant naming (LI-Small vs LI-Medium) and header casing
    (``LI-Medium_accounts.csv`` vs ``..._Accounts.csv``): matches the one file whose name
    contains "trans" and the one containing "account", case-insensitively. Raises if the
    directory doesn't hold exactly one of each, so a wrong upload fails loudly rather than
    silently reading the wrong file.
    """
    raw = Path(raw_dir)
    csvs = sorted(raw.glob("*.csv"))
    trans = [p for p in csvs if "trans" in p.name.lower()]
    accounts = [p for p in csvs if "account" in p.name.lower()]
    if len(trans) != 1 or len(accounts) != 1:
        raise FileNotFoundError(
            f"expected exactly one *trans*.csv and one *account*.csv in {raw}; found "
            f"trans={[p.name for p in trans]}, accounts={[p.name for p in accounts]}"
        )
    return trans[0], accounts[0]


def load_accounts(path: str | Path) -> pd.DataFrame:
    """Read the accounts file and return a verified ``Bank ID -> Bank Name`` mapping.

    The join rule requires every Bank ID to map to exactly one Bank
    Name — this is asserted, not assumed, because a many-to-one violation would corrupt
    the institution assignment.
    """
    accounts = pd.read_csv(path)
    pairs = accounts[["Bank ID", "Bank Name"]].drop_duplicates()
    ambiguous = pairs.groupby("Bank ID")["Bank Name"].nunique()
    bad = ambiguous[ambiguous > 1]
    if not bad.empty:
        raise ValueError(
            f"Bank ID -> Bank Name is not unambiguous for {len(bad)} bank ids "
            f"(e.g. {list(bad.index[:3])}); cannot join safely."
        )
    return pairs.reset_index(drop=True)


def build_bank_name_map(accounts_pairs: pd.DataFrame) -> dict[int, str]:
    """Turn the verified pairs into a ``{bank_id: bank_name}`` dict."""
    return dict(zip(accounts_pairs["Bank ID"], accounts_pairs["Bank Name"], strict=True))


def normalise_transactions(raw: pd.DataFrame) -> pd.DataFrame:
    """Rename raw headers to canonical snake_case and type the key columns.

    Tolerant of the IBM files' duplicated positional ``Account`` header: if the exact
    ``From Account`` / ``To Account`` names are absent, the 3rd and 5th columns are used
    (the documented raw layout).
    """
    df = raw.copy()
    # Handle the duplicated-"Account"-header quirk before the rename map runs.
    if "From Account" not in df.columns and "Account" in df.columns:
        cols = list(df.columns)
        # Raw order: Timestamp, From Bank, Account, To Bank, Account.1, ...
        df = df.rename(columns={cols[2]: "From Account", cols[4]: "To Account"})
    df = df.rename(columns=RAW_TO_CANONICAL)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["is_laundering"] = df["is_laundering"].astype(int)
    for col in ("from_bank", "to_bank"):
        df[col] = df[col].astype(int)
    for col in ("amount_paid", "amount_received"):
        if col in df.columns:
            df[col] = df[col].astype(float)
    return df


def join_bank_names(trans: pd.DataFrame, bank_name_map: dict[int, str]) -> pd.DataFrame:
    """Attach ``from_bank_name`` / ``to_bank_name`` via the verified mapping."""
    df = trans.copy()
    df["from_bank_name"] = df["from_bank"].map(bank_name_map)
    df["to_bank_name"] = df["to_bank"].map(bank_name_map)
    missing = df["from_bank_name"].isna().sum() + df["to_bank_name"].isna().sum()
    if missing:
        raise ValueError(f"{missing} transactions reference a bank id absent from accounts.")
    return df


def load_and_label(trans_path: str | Path, accounts_path: str | Path) -> pd.DataFrame:
    """Full load step: read raw files, normalise, join bank names, keep the label.

    Returns the canonical joined+labelled transaction table (schema.JOINED_COLUMNS).
    Reads the whole file into memory — fine for the sample/tests, but use ``stream_load``
    for the full ~31M-row LI-Medium file on limited RAM.
    """
    accounts_pairs = load_accounts(accounts_path)
    bank_name_map = build_bank_name_map(accounts_pairs)
    trans = normalise_transactions(pd.read_csv(trans_path))
    return join_bank_names(trans, bank_name_map)


def _accumulate_bank_stats(chunk: pd.DataFrame, acc: dict) -> None:
    """Fold one chunk into running exact per-bank accumulators (sender + receiver)."""
    part = pd.concat(
        [
            chunk[["from_bank", "amount_paid", "payment_currency", "is_laundering"]].rename(
                columns={"from_bank": "bank"}
            ),
            chunk[["to_bank", "amount_paid", "payment_currency", "is_laundering"]].rename(
                columns={"to_bank": "bank"}
            ),
        ],
        ignore_index=True,
    )
    g = part.groupby("bank")
    acc["count"] = acc["count"].add(g.size(), fill_value=0)
    acc["fraud"] = acc["fraud"].add(g["is_laundering"].sum(), fill_value=0)
    acc["amount"] = acc["amount"].add(g["amount_paid"].sum(), fill_value=0)
    for bank, currencies in part.groupby("bank")["payment_currency"]:
        acc["currencies"].setdefault(bank, set()).update(currencies.unique())


def _finalise_bank_stats(acc: dict) -> pd.DataFrame:
    """Turn the accumulators into the per-bank stats table clustering expects."""
    count = acc["count"]
    return pd.DataFrame(
        {
            "bank_id": count.index.astype(int),
            "txn_count": count.to_numpy(dtype=int),
            "amount_mean": (acc["amount"] / count).to_numpy(dtype=float),
            "fraud_rate": (acc["fraud"] / count).to_numpy(dtype=float),
            "currency_count": [len(acc["currencies"][b]) for b in count.index],
        }
    )


def stream_load(
    trans_path: str | Path,
    accounts_path: str | Path,
    *,
    reservoir_size: int = 1_000_000,
    chunksize: int = 1_000_000,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    """Memory-bounded load for the full LI-Medium file on limited RAM.

    Streams the CSV in chunks and returns ``(uniform, laundering, bank_stats, n_total)``:

    - ``uniform`` — a uniform random sample of ~``reservoir_size`` rows over the **whole**
      file (background pool for the chain-preserving sample). Drawn by keeping the rows
      with the smallest random keys seen so far — an exact uniform sample.
    - ``laundering`` — **every** laundering row, so whole chains are available.
    - ``bank_stats`` — **exact** per-bank stats over *all* banks (unbiased, full coverage,
      so every bank in the sample maps to an institution). Accumulated, not sampled.
    - ``n_total`` — total row count, so the true base rate (len(laundering)/n_total) is
      known for base-rate-preserving sampling.

    Peak memory is bounded by ``reservoir_size + chunksize`` rows plus all laundering rows
    and the per-bank accumulators — never the full dataset.
    """
    bank_name_map = build_bank_name_map(load_accounts(accounts_path))
    rng = np.random.default_rng(seed)
    reservoir: pd.DataFrame | None = None
    laundering_parts: list[pd.DataFrame] = []
    acc = {
        "count": pd.Series(dtype="float64"),
        "fraud": pd.Series(dtype="float64"),
        "amount": pd.Series(dtype="float64"),
        "currencies": {},
    }
    n_total = 0

    for chunk in pd.read_csv(trans_path, chunksize=chunksize):
        c = join_bank_names(normalise_transactions(chunk), bank_name_map)
        n_total += len(c)
        _accumulate_bank_stats(c, acc)
        laundering_parts.append(c[c["is_laundering"] == 1])
        c = c.assign(_key=rng.random(len(c)))
        reservoir = c if reservoir is None else pd.concat([reservoir, c], ignore_index=True)
        if len(reservoir) > reservoir_size:
            reservoir = reservoir.nsmallest(reservoir_size, "_key")

    if reservoir is None:  # empty file
        empty = pd.DataFrame(columns=[*RAW_TO_CANONICAL.values(), "from_bank_name", "to_bank_name"])
        stat_cols = ["bank_id", "txn_count", "amount_mean", "fraud_rate", "currency_count"]
        return empty, empty, pd.DataFrame(columns=stat_cols), 0
    uniform = reservoir.drop(columns="_key").reset_index(drop=True)
    laundering = pd.concat(laundering_parts, ignore_index=True)
    return uniform, laundering, _finalise_bank_stats(acc), n_total
