"""Data-foundation tests — chain integrity, non-IID, ownership column, window split.

These run on small synthetic fixtures (no 31M-row dataset needed) and protect the
invariants the real full-data run must uphold: chains are never partially dropped, the
partition is non-IID, every row carries its owning-institution hook, and the train/detect
windows never overlap.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from acn.data import cluster, load, partition, report, sample, split_windows
from acn.data.schema import INSTITUTIONS


# --------------------------------------------------------------------------- load
def _write_raw(tmp_path, ambiguous=False):
    trans = pd.DataFrame(
        {
            "Timestamp": ["2022-09-02 10:00:00", "2022-09-03 11:00:00"],
            "From Bank": [10, 20],
            "From Account": ["A1", "A2"],
            "To Bank": [20, 10],
            "To Account": ["A2", "A1"],
            "Amount Received": [100.0, 200.0],
            "Receiving Currency": ["INR", "INR"],
            "Amount Paid": [100.0, 200.0],
            "Payment Currency": ["INR", "USD"],
            "Payment Format": ["ACH", "Wire"],
            "Is Laundering": [0, 1],
        }
    )
    accounts = pd.DataFrame(
        {
            "Bank ID": [10, 20, 20] + ([10] if ambiguous else []),
            "Bank Name": ["Alpha", "Beta", "Beta"] + (["AlphaX"] if ambiguous else []),
            "Account Number": ["A1", "A2", "A3"] + (["A9"] if ambiguous else []),
        }
    )
    tp, ap = tmp_path / "trans.csv", tmp_path / "acc.csv"
    trans.to_csv(tp, index=False)
    accounts.to_csv(ap, index=False)
    return tp, ap


def test_load_and_label_joins_bank_names(tmp_path):
    tp, ap = _write_raw(tmp_path)
    df = load.load_and_label(tp, ap)
    assert list(df["is_laundering"]) == [0, 1]  # label preserved at txn level
    assert df.loc[df["from_bank"] == 10, "from_bank_name"].iloc[0] == "Alpha"
    assert df["to_bank_name"].notna().all()


def test_load_rejects_ambiguous_bank_mapping(tmp_path):
    tp, ap = _write_raw(tmp_path, ambiguous=True)
    with pytest.raises(ValueError, match="unambiguous"):
        load.load_and_label(tp, ap)


def test_find_raw_files_tolerates_variant_naming_and_casing(tmp_path):
    # Real-world upload: LI-Medium with lowercase 'accounts' — must still be found.
    (tmp_path / "LI-Medium_Trans.csv").write_text("x\n")
    (tmp_path / "LI-Medium_accounts.csv").write_text("y\n")
    trans, accounts = load.find_raw_files(tmp_path)
    assert trans.name == "LI-Medium_Trans.csv"
    assert accounts.name == "LI-Medium_accounts.csv"


def test_find_raw_files_raises_on_wrong_upload(tmp_path):
    # Only a transactions file present -> fail loudly, don't silently proceed.
    (tmp_path / "LI-Small_Trans.csv").write_text("x\n")
    with pytest.raises(FileNotFoundError, match="account"):
        load.find_raw_files(tmp_path)


def test_stream_load_keeps_all_laundering_and_bounds_uniform(tmp_path):
    # 60 rows across chunks: stream_load must return every laundering row and a
    # uniform sample capped at reservoir_size — never the whole file.
    n = 60
    banks = [10 + (i % 4) for i in range(n)]
    trans = pd.DataFrame(
        {
            "Timestamp": ["2022-09-02 10:00:00"] * n,
            "From Bank": banks,
            "From Account": [f"A{i}" for i in range(n)],
            "To Bank": [banks[(i + 1) % n] for i in range(n)],
            "To Account": [f"A{(i + 1) % n}" for i in range(n)],
            "Amount Received": [100.0] * n,
            "Receiving Currency": ["INR"] * n,
            "Amount Paid": [100.0] * n,
            "Payment Currency": ["INR"] * n,
            "Payment Format": ["ACH"] * n,
            "Is Laundering": [1 if i % 10 == 0 else 0 for i in range(n)],  # 6 laundering
        }
    )
    accounts = pd.DataFrame(
        {
            "Bank ID": [10, 11, 12, 13],
            "Bank Name": ["B10", "B11", "B12", "B13"],
            "Account Number": ["x", "y", "z", "w"],
        }
    )
    tp, ap = tmp_path / "t.csv", tmp_path / "a.csv"
    trans.to_csv(tp, index=False)
    accounts.to_csv(ap, index=False)

    uniform, laundering, bank_stats, n_total = load.stream_load(
        tp, ap, reservoir_size=25, chunksize=7, seed=42
    )
    assert len(laundering) == 6  # every laundering row available (chains preserved later)
    assert (laundering["is_laundering"] == 1).all()
    assert len(uniform) == 25  # capped at reservoir_size, not all 60
    assert "from_bank_name" in uniform.columns  # joined + normalised
    assert n_total == 60  # exact total for the true base rate
    # bank_stats covers every bank (all 4), so no sample bank can go unmapped.
    assert set(bank_stats["bank_id"]) == {10, 11, 12, 13}
    assert set(bank_stats.columns) >= {"txn_count", "amount_mean", "fraud_rate", "currency_count"}


# ------------------------------------------------------------------------- cluster
def test_assign_amount_stratified_balanced_and_no_empty_institution():
    # 25 banks with increasing amount profiles and equal volume. The partition must:
    # (1) fill all 5 institutions (none empty — the earlier failure mode),
    # (2) balance transaction volume across them,
    # (3) give each a distinct amount range, ordered INST_A (smallest) -> INST_E (largest).
    n = 25
    bank_stats = pd.DataFrame(
        {
            "bank_id": range(n),
            "txn_count": [100] * n,
            "amount_mean": [1000.0 * (i + 1) for i in range(n)],
            "fraud_rate": [0.1 if i % 5 == 0 else 0.0 for i in range(n)],
            "currency_count": [2] * n,
        }
    )
    out = cluster.assign_institutions(bank_stats, seed=42)
    assert out["institution"].notna().all()  # coverage
    counts = out.groupby("institution").size()
    assert set(counts.index) == set(INSTITUTIONS)  # all 5 present
    assert (counts > 0).all()  # none empty

    vol = out.groupby("institution")["txn_count"].sum()
    assert vol.max() / vol.min() < 1.5  # volume balanced

    amt = out.groupby("institution")["amount_mean"].mean()
    ordered = [amt[inst] for inst in INSTITUTIONS]
    assert ordered == sorted(ordered)  # distinct, increasing amount profiles (non-IID)
    assert amt["INST_E"] > amt["INST_A"] * 2  # genuinely different, not homogeneous


def test_assign_requires_at_least_five_banks():
    bank_stats = pd.DataFrame(
        {
            "bank_id": [1, 2, 3],
            "txn_count": [1, 2, 3],
            "amount_mean": [1, 2, 3],
            "fraud_rate": [0.1, 0.2, 0.3],
            "currency_count": [1, 2, 3],
        }
    )
    with pytest.raises(ValueError, match="at least"):
        cluster.assign_institutions(bank_stats, seed=42)


def test_per_bank_stats_counts_participation():
    df = pd.DataFrame(
        {
            "from_bank": [1, 1, 2],
            "to_bank": [2, 2, 1],
            "amount_paid": [10.0, 20.0, 30.0],
            "payment_currency": ["INR", "USD", "INR"],
            "is_laundering": [0, 1, 0],
        }
    )
    stats = cluster.per_bank_stats(df).set_index("bank_id")
    # bank 1 participates in all 3 txns (2 as sender, 1 as receiver).
    assert stats.loc[1, "txn_count"] == 3
    assert stats.loc[1, "currency_count"] == 2


# -------------------------------------------------------------------------- sample
def _chain_df():
    # Two independent laundering chains + background rows.
    rows = [
        # chain 1: A->B->C
        ("2022-09-02", 1, "A", 2, "B", 1),
        ("2022-09-02", 2, "B", 3, "C", 1),
        # chain 2: X->Y
        ("2022-09-03", 4, "X", 5, "Y", 1),
        # background
        ("2022-09-04", 1, "A", 6, "Z", 0),
        ("2022-09-05", 6, "Z", 1, "A", 0),
    ]
    cols = ["timestamp", "from_bank", "from_account", "to_bank", "to_account", "is_laundering"]
    return pd.DataFrame(rows, columns=cols).assign(
        timestamp=lambda d: pd.to_datetime(d["timestamp"]), amount_paid=100.0
    )


def test_identify_chains_finds_two_components():
    df = _chain_df()
    assert sample.count_chains(df) == 2
    chains = sample.identify_chains(df)
    # the two chain-1 rows share a chain id; chain-2 row differs; background = -1.
    assert chains.iloc[0] == chains.iloc[1]
    assert chains.iloc[0] != chains.iloc[2]
    assert (chains[df["is_laundering"] == 0] == -1).all()


def test_chain_preserving_sample_selects_whole_chains():
    df = _chain_df()
    # rid tags each laundering row so we can check whole-chain integrity after sampling.
    laund = df[df["is_laundering"] == 1].reset_index(drop=True)
    laund = laund.assign(rid=range(len(laund)))
    background = df[df["is_laundering"] == 0]
    # chain of each rid: rows 0,1 form one chain (A-B-C); row 2 is a separate chain.
    chain_of = dict(zip(laund["rid"], sample.identify_chains(laund).to_numpy(), strict=True))

    out = sample.chain_preserving_sample(laund, background, target_rows=4, base_rate=0.5, seed=42)
    sel = set(out.loc[out["is_laundering"] == 1, "rid"])
    # Every chain that contributes any row must be fully present — no partial chain.
    for cid in {chain_of[r] for r in sel}:
        chain_rids = {r for r, c in chain_of.items() if c == cid}
        assert chain_rids <= sel


def test_chain_preserving_sample_preserves_base_rate():
    # 40 background + 5 single-row laundering chains; a 0.10 base rate on 20 rows
    # should select ~2 laundering rows (whole chains), not all 5.
    laund = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2022-09-02"] * 5),
            "from_bank": range(5),
            "from_account": [f"L{i}" for i in range(5)],
            "to_bank": range(5, 10),
            "to_account": [f"R{i}" for i in range(5)],
            "is_laundering": 1,
            "amount_paid": 100.0,
        }
    )
    background = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2022-09-03"] * 40),
            "from_bank": 99,
            "from_account": "bg",
            "to_bank": 98,
            "to_account": "bg2",
            "is_laundering": 0,
            "amount_paid": 100.0,
        }
    )
    out = sample.chain_preserving_sample(laund, background, target_rows=20, base_rate=0.10, seed=42)
    assert len(out) == 20
    assert int(out["is_laundering"].sum()) == 2  # round(20 * 0.10), whole chains


def test_train_detect_samples_keep_chains_whole():
    # Two multi-hop chains that unfold ACROSS the old train/detect time boundary — the exact case
    # the old time-split shredded. Chain 1: A->B->C->D (spans Sep 9-12). Chain 2: E->F->G (Sep 13).
    # Plus 4 isolated single transactions.
    rows = [
        ("2022-09-09", 1, "A", 2, "B"),  # chain 1
        ("2022-09-10", 2, "B", 3, "C"),
        ("2022-09-12", 3, "C", 4, "D"),
        ("2022-09-13", 5, "E", 6, "F"),  # chain 2
        ("2022-09-13", 6, "F", 7, "G"),
    ]
    rows += [("2022-09-13", 10 + i, f"X{i}", 20 + i, f"Y{i}") for i in range(4)]  # singles
    laund = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([r[0] for r in rows]),
            "from_bank": [r[1] for r in rows],
            "from_account": [r[2] for r in rows],
            "to_bank": [r[3] for r in rows],
            "to_account": [r[4] for r in rows],
            "is_laundering": 1,
            "amount_paid": 100.0,
        }
    )
    background = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2022-09-13"] * 5000),
            "from_bank": 99,
            "from_account": "bg",
            "to_bank": 98,
            "to_account": "bg2",
            "is_laundering": 0,
            "amount_paid": 100.0,
        }
    )
    train, detect = sample.build_train_detect_samples(
        laund,
        background,
        base_rate=0.0005,
        seed=42,
        train_target=2000,
        detect_target=2000,
        detect_multihop_chains=1,
        detect_single_chains=2,
    )
    # No laundering row is lost or duplicated across the two sets.
    assert int(train["is_laundering"].sum()) + int(detect["is_laundering"].sum()) == len(laund)
    # Chain integrity: chain 1's accounts (A,B,C,D) must land ENTIRELY in one set, never split.
    chain1 = {"A", "B", "C", "D"}
    tr_acc = set(train.loc[train.is_laundering == 1, "from_account"]) | set(
        train.loc[train.is_laundering == 1, "to_account"]
    )
    de_acc = set(detect.loc[detect.is_laundering == 1, "from_account"]) | set(
        detect.loc[detect.is_laundering == 1, "to_account"]
    )
    assert chain1.issubset(tr_acc) or chain1.issubset(de_acc)  # whole, not split
    assert not (chain1 & tr_acc and chain1 & de_acc)  # never in both
    # detect got exactly its one requested multi-hop chain (3 hops = 3 laundering rows)
    assert int(detect["is_laundering"].sum()) >= 3


def test_sample_is_reproducible_for_a_seed():
    df = _chain_df()
    laund, background = df[df["is_laundering"] == 1], df[df["is_laundering"] == 0]
    a = sample.chain_preserving_sample(laund, background, target_rows=4, base_rate=0.5, seed=42)
    b = sample.chain_preserving_sample(laund, background, target_rows=4, base_rate=0.5, seed=42)
    pd.testing.assert_frame_equal(a, b)


# ----------------------------------------------------------------------- partition
def test_partition_adds_non_null_dst_institution():
    df = _chain_df()
    bank_to_inst = {1: "INST_A", 2: "INST_B", 3: "INST_C", 4: "INST_D", 5: "INST_E", 6: "INST_A"}
    parts = partition.partition(df, bank_to_inst)
    for inst, sub in parts.items():
        if sub.empty:
            continue
        assert sub["dst_institution"].notna().all()
        assert (sub["src_institution"] == inst).all()


def test_dst_institution_is_owning_institution_of_to_bank():
    df = _chain_df()
    bank_to_inst = {1: "INST_A", 2: "INST_B", 3: "INST_C", 4: "INST_D", 5: "INST_E", 6: "INST_A"}
    enriched = partition.add_institution_columns(df, bank_to_inst)
    row = enriched.iloc[0]  # to_bank == 2 -> INST_B
    assert row["dst_institution"] == "INST_B"


# ------------------------------------------------------------------- window split
def test_window_split_has_no_overlap():
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2022-09-09 08:00:00",
                    "2022-09-10 23:59:59",
                    "2022-09-11 00:00:00",
                    "2022-09-16 20:00:00",
                ]
            ),
            "is_laundering": [0, 0, 1, 1],
        }
    )
    train, detect = split_windows.split_train_detect(df)
    assert (pd.to_datetime(train["timestamp"]) < pd.Timestamp("2022-09-11")).all()
    assert (pd.to_datetime(detect["timestamp"]) >= pd.Timestamp("2022-09-11")).all()
    assert len(train) == 2 and len(detect) == 2


# ---------------------------------------------------------------------- non-IID
def test_non_iid_partitions_have_divergent_distributions():
    # INST_A: small amounts, low fraud; INST_E: large amounts, high fraud.
    a = pd.DataFrame({"amount_paid": [1e3] * 50, "is_laundering": [0] * 50})
    e = pd.DataFrame({"amount_paid": [2e6] * 50, "is_laundering": [1] * 25 + [0] * 25})
    parts = {"INST_A": a, "INST_B": a, "INST_C": a, "INST_D": a, "INST_E": e}
    rates = report.institution_fraud_rates(parts)
    assert rates["INST_E"] > rates["INST_A"]  # non-IID fraud
    assert report.mean_kl_vs_pooled(parts) > 0.01  # distributions differ


def test_iid_partitions_have_near_zero_divergence():
    same = pd.DataFrame({"amount_paid": [1e4] * 40, "is_laundering": [0] * 40})
    parts = {k: same.copy() for k in ["INST_A", "INST_B", "INST_C", "INST_D", "INST_E"]}
    assert report.mean_kl_vs_pooled(parts) < 1e-6


def test_kl_divergence_zero_for_identical():
    p = np.array([0.25, 0.25, 0.25, 0.25])
    assert report.kl_divergence(p, p) == pytest.approx(0.0, abs=1e-9)
    assert report.kl_divergence(np.array([0.9, 0.1]), np.array([0.1, 0.9])) > 0
