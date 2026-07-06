"""Chain-preserving 1% sample.

A naive 1% row sample shatters laundering chains and destroys the signal. Instead we
identify chains (connected components of the laundering sub-graph) and sample **whole
chains**, so no chain is partially dropped, then top up with background transactions to
~310K rows while preserving the true (~0.052%) fraud base rate. Chain counts are recorded.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd

DEFAULT_TARGET_ROWS = 310_000
SAMPLE_SEED = 42  # fixed so the ~310K sample is reproducible before partitioning


def _account_node(bank: int, account: str) -> str:
    """A globally-unique node key for an account (bank-scoped)."""
    return f"{bank}:{account}"


def identify_chains(df: pd.DataFrame) -> pd.Series:
    """Label each laundering transaction with its chain id; non-laundering rows get -1.

    A chain is a connected component in the graph whose edges are the laundering
    transactions (from-account -> to-account). Only laundering rows enter the graph, so
    this stays cheap even on the full dataset.
    """
    chain_id = pd.Series(-1, index=df.index, dtype=int)
    laundering = df[df["is_laundering"] == 1]
    if laundering.empty:
        return chain_id

    graph = nx.Graph()
    for idx, row in laundering.iterrows():
        src = _account_node(row["from_bank"], row["from_account"])
        dst = _account_node(row["to_bank"], row["to_account"])
        if not graph.has_edge(src, dst):
            graph.add_edge(src, dst, indices=[])
        graph[src][dst]["indices"].append(idx)

    for component_id, component in enumerate(nx.connected_components(graph)):
        sub = graph.subgraph(component)
        for _, _, data in sub.edges(data=True):
            chain_id.loc[data["indices"]] = component_id
    return chain_id


def count_chains(df: pd.DataFrame) -> int:
    """Number of distinct laundering chains (connected components)."""
    chains = identify_chains(df)
    distinct = set(chains.unique()) - {-1}
    return len(distinct)


def chain_preserving_sample(
    laundering: pd.DataFrame,
    background: pd.DataFrame,
    target_rows: int = DEFAULT_TARGET_ROWS,
    base_rate: float | None = None,
    seed: int = SAMPLE_SEED,
) -> pd.DataFrame:
    """Sample **whole laundering chains** + background, preserving the true base rate.

    A realistic base rate (~0.052% for LI-Medium) is essential — the evaluation's
    precision/alerts-per-day only mean something at the real rate, so we must NOT keep
    every laundering row (that would inflate fraud ~100x). Instead:

    - target ``round(target_rows * base_rate)`` laundering rows,
    - select **whole chains** (connected components) at random until that count is
      reached, so no chain is ever partially included,
    - fill the rest with a seeded background sample to hit ``target_rows``.

    ``base_rate`` defaults to the rate within ``laundering ∪ background`` if not given, but
    for the streamed full file pass the true ``len(laundering)/n_total`` (the background
    here is only a uniform *sample*, so its local rate is not the population rate).
    """
    if base_rate is None:
        total = len(laundering) + len(background)
        base_rate = (len(laundering) / total) if total else 0.0
    target_laundering = max(1, round(target_rows * base_rate))

    chain_ids = identify_chains(laundering)
    laund = laundering.assign(_chain=chain_ids.to_numpy())
    groups = [g for _, g in laund.groupby("_chain")]

    rng = np.random.default_rng(seed)
    rng.shuffle(groups)
    selected: list[pd.DataFrame] = []
    kept = 0
    for g in groups:
        selected.append(g)
        kept += len(g)
        if kept >= target_laundering:
            break
    selected_laundering = (
        pd.concat(selected).drop(columns="_chain") if selected else laundering.iloc[:0]
    )

    n_background = max(target_rows - len(selected_laundering), 0)
    n_background = min(n_background, len(background))
    sampled_bg = background.sample(n=n_background, random_state=seed)

    out = pd.concat([selected_laundering, sampled_bg]).sort_values("timestamp")
    return out.reset_index(drop=True)


def _chain_account_counts(laund: pd.DataFrame) -> dict[int, int]:
    """Unique-account count per chain id (``_chain`` column) — used to pick multi-hop chains."""
    counts: dict[int, int] = {}
    for cid, g in laund.groupby("_chain"):
        accts = set(zip(g["from_bank"], g["from_account"], strict=False)) | set(
            zip(g["to_bank"], g["to_account"], strict=False)
        )
        counts[int(cid)] = len(accts)
    return counts


def build_train_detect_samples(
    laundering: pd.DataFrame,
    background: pd.DataFrame,
    base_rate: float,
    seed: int = SAMPLE_SEED,
    train_target: int = 250_000,
    detect_target: int = 600_000,
    detect_multihop_chains: int = 200,
    detect_single_chains: int = 300,
    min_multihop_accounts: int = 3,
    max_detect_chain_accounts: int = 200,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Two samples that keep laundering **chains whole** — dense train, chain-rich detect.

    The earlier version split laundering by the detect-window *timestamp*, which shredded every
    multi-hop chain that unfolded across the train/detect boundary (a chain survives only if all
    its hops fall in the window) — so the detect set ended up with almost no chains to detect.

    Instead we identify chains on the **full** laundering set (chains intact), then assign each
    **whole** chain to train or detect, never splitting one:

    - **detect** gets ``detect_multihop_chains`` real multi-hop chains (≥ ``min_multihop_accounts``
      accounts, capped at ``max_detect_chain_accounts`` so a giant component doesn't dominate) plus
      some short chains for realism — this is what actually gives the detection layers cross-bank
      layering to find — then background up to ``detect_target`` rows.
    - **train** gets every remaining chain (dense positives for GraphSAGE) + background.

    The detect base rate runs a bit above the theoretical 0.05% (whole chains + a bounded number of
    negatives), a deliberate, documented trade so detection is testable; report metrics at the
    actual rate. ``base_rate`` is accepted for signature stability but the split is chain-driven.
    """
    rng = np.random.default_rng(seed)
    chain_ids = identify_chains(laundering)
    laund = laundering.assign(_chain=chain_ids.to_numpy())
    accts = _chain_account_counts(laund)

    multihop = [
        c for c, n in accts.items() if min_multihop_accounts <= n <= max_detect_chain_accounts
    ]
    singles = [c for c, n in accts.items() if n < min_multihop_accounts]
    rng.shuffle(multihop)
    rng.shuffle(singles)

    detect_chain_ids = set(multihop[:detect_multihop_chains]) | set(singles[:detect_single_chains])
    is_detect = laund["_chain"].isin(detect_chain_ids)
    laund_detect = laund[is_detect].drop(columns="_chain")
    laund_train = laund[~is_detect].drop(columns="_chain")

    # disjoint background pools for the two sets (shuffle once, split)
    bg = background.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    n_bg_detect = min(max(detect_target - len(laund_detect), 0), len(bg))
    bg_detect = bg.iloc[:n_bg_detect]
    bg_train_pool = bg.iloc[n_bg_detect:]
    n_bg_train = min(max(train_target - len(laund_train), 0), len(bg_train_pool))
    bg_train = bg_train_pool.iloc[:n_bg_train]

    train_sample = (
        pd.concat([laund_train, bg_train]).sort_values("timestamp").reset_index(drop=True)
    )
    detect_sample = (
        pd.concat([laund_detect, bg_detect]).sort_values("timestamp").reset_index(drop=True)
    )
    return train_sample, detect_sample
