"""Build the data foundation locally on the Mac.

Streams the full LI-Medium file, assigns banks to the 5 institutions, builds the dense-train /
chain-rich-detect samples (whole laundering chains — the chain-fragmentation fix), and
writes per-institution train/detect splits. Everything runs in-place on the Mac; the full 31M
file streams in ~70s with bounded memory.

Usage:
    python scripts/build_dataset.py --raw-dir acn-data/data/raw \\
        --out-dir acn-data/data --seed 42
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acn.data import cluster, load, partition, report, sample  # noqa: E402
from acn.data.schema import INSTITUTIONS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Build ACN data foundation locally.")
    ap.add_argument("--raw-dir", default="acn-data/data/raw")
    ap.add_argument("--out-dir", default="acn-data/data")
    ap.add_argument("--logs-dir", default="acn-data/logs")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--reservoir", type=int, default=1_200_000)
    ap.add_argument("--train-target", type=int, default=250_000)
    ap.add_argument("--detect-target", type=int, default=600_000)
    args = ap.parse_args()

    raw = Path(args.raw_dir)
    out = Path(args.out_dir)
    processed, splits, logs = out / "processed", out / "splits", Path(args.logs_dir)
    for d in (processed, splits / "train", splits / "detect", logs):
        d.mkdir(parents=True, exist_ok=True)

    trans_path, accounts_path = load.find_raw_files(raw)
    print(f"[data] streaming {trans_path.name} + {accounts_path.name} …")
    uniform, laundering, bank_stats, n_total = load.stream_load(
        trans_path,
        accounts_path,
        reservoir_size=args.reservoir,
        chunksize=2_000_000,
        seed=args.seed,
    )
    base_rate = len(laundering) / n_total
    print(f"[data] {n_total:,} rows | laundering {len(laundering):,} | base rate {base_rate:.5%}")

    assignment = cluster.assign_institutions(bank_stats, seed=args.seed)
    assignment.to_parquet(processed / "bank_clusters.parquet")
    bank_to_inst = cluster.bank_to_institution(assignment)

    background = uniform[uniform["is_laundering"] == 0]
    train_sample, detect_sample = sample.build_train_detect_samples(
        laundering,
        background,
        base_rate=base_rate,
        seed=args.seed,
        train_target=args.train_target,
        detect_target=args.detect_target,
    )
    tl, dl = train_sample["is_laundering"], detect_sample["is_laundering"]
    print(
        f"[data] TRAIN : {len(train_sample):,} rows | laundering {int(tl.sum()):,} "
        f"({tl.mean():.3%})"
    )
    print(
        f"[data] DETECT: {len(detect_sample):,} rows | laundering {int(dl.sum()):,} "
        f"({dl.mean():.4%})"
    )
    train_sample.to_parquet(processed / "train_sample.parquet")
    detect_sample.to_parquet(processed / "detect_sample.parquet")

    train_parts = partition.partition(train_sample, bank_to_inst)
    detect_parts = partition.partition(detect_sample, bank_to_inst)
    for inst in INSTITUTIONS:
        train_parts[inst].to_parquet(splits / "train" / f"{inst}.parquet")
        detect_parts[inst].to_parquet(splits / "detect" / f"{inst}.parquet")
        tr, de = train_parts[inst], detect_parts[inst]
        print(
            f"  {inst}: train {len(tr):,} (laundering {int(tr['is_laundering'].sum())}) | "
            f"detect {len(de):,} (laundering {int(de['is_laundering'].sum())})"
        )

    (logs / "data_foundation_report.md").write_text(
        report.build_report(detect_sample, detect_parts, seed=args.seed)
    )
    print(f"[data] wrote splits to {splits} and report to {logs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
