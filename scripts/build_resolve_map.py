"""Populate each institution's owner-side hash -> account resolution map (into Redis).

Run per institution, on that institution's own transactions: it hashes the accounts it owns the
same ownership way the pseudonymiser does and stores the inverse under ``resolve:{institution}``.
Conceptually each map lives inside its owning bank and is never shared; on one machine it is a
single Redis with per-institution namespaces. This is what lets a filing officer resolve *their
own* accounts for an STR without anyone being able to reverse another bank's hashes.

Env: ACN_SHARED_SALT, REDIS_URL. Usage:
    ACN_SHARED_SALT=... python scripts/build_resolve_map.py --splits-dir acn-data/data/splits/detect
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acn import redis_client as redis_store  # noqa: E402
from acn.casemgmt import resolve  # noqa: E402
from acn.data.schema import INSTITUTIONS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Build owner-side hash->account resolution maps.")
    ap.add_argument("--splits-dir", default="acn-data/data/splits/detect")
    args = ap.parse_args()

    salt = os.environ.get("ACN_SHARED_SALT")
    if not salt:
        print("ERROR: ACN_SHARED_SALT is not set.")
        return 1

    splits = Path(args.splits_dir)
    r = redis_store.connect()
    total = 0
    for inst in INSTITUTIONS:
        part = splits / f"{inst}.parquet"
        if not part.exists():
            print(f"skip {inst}: {part} not found")
            continue
        n = resolve.build_from_partition(r, inst, pd.read_parquet(part), salt)
        print(f"{inst}: {n:,} owned accounts resolvable")
        total += n
    print(f"total resolution entries: {total:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
