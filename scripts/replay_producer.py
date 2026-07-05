"""Replay the detect window as pseudonymised edges.

Runs each institution's producer on the local Mac: reads its detect-window partition,
pseudonymises each transaction in-process (ownership HMAC hashing, fixed buckets, threshold
proximity), and publishes only pseudonymised edges to its own ``edges_INST_X`` topic over the
mTLS listener — plus a per-window count commitment. Raw transactions never reach the broker
.

Prereqs: the stack is up (``docker compose up -d``), the detect splits are available locally
(download ``data/splits/detect/`` from Drive), the mTLS certs exist (``scripts/gen_certs.sh``),
and ``ACN_SHARED_SALT`` is set.

Usage:
    ACN_SHARED_SALT=... python scripts/replay_producer.py \\
        --splits-dir ./data/splits/detect --certs-dir ./certs/kafka \\
        --broker localhost:9093 --rate 50
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acn.data.schema import INSTITUTIONS  # noqa: E402
from acn.pseudonymise import producer  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay detect-window edges to Kafka.")
    parser.add_argument("--splits-dir", required=True, help="Local dir with detect INST_*.parquet")
    parser.add_argument("--certs-dir", default="certs/kafka", help="mTLS cert dir")
    parser.add_argument("--broker", default="localhost:9093", help="Kafka mTLS listener")
    parser.add_argument("--rate", type=float, default=None, help="Edges/sec (throttle for a demo)")
    args = parser.parse_args()

    salt = os.environ.get("ACN_SHARED_SALT")
    if not salt:
        print("ERROR: ACN_SHARED_SALT is not set.")
        return 1
    splits, certs = Path(args.splits_dir), Path(args.certs_dir)

    total = 0
    for inst in INSTITUTIONS:
        part = splits / f"{inst}.parquet"
        if not part.exists():
            print(f"skip {inst}: {part} not found")
            continue
        cfg = producer.ssl_config(
            args.broker,
            str(certs / "ca-cert.pem"),
            str(certs / f"{inst}-cert.pem"),
            str(certs / f"{inst}-key.pem"),
        )
        n = producer.replay_partition(inst, pd.read_parquet(part), salt, cfg, rate=args.rate)
        print(f"{inst}: published {n} edges to edges_{inst} (+ count commitment)")
        total += n
    print(f"total edges published: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
