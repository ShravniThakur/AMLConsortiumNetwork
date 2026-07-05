"""Fixed amount buckets + threshold-proximity flag.

Amounts are replaced by a **fixed, shared** bucket index — never the raw value. The
boundaries are identical across all institutions so cross-institution flow-conservation
scoring is meaningful (randomised/per-institution buckets would break it). A binary
threshold-proximity flag surfaces structuring near the ₹10 lakh reporting line without
revealing the amount.
"""

from __future__ import annotations

import bisect

# Fixed boundaries: ₹10K, ₹25K, ₹50K, ₹100K, ₹250K, ₹500K, ₹10L, ₹25L, ₹50L.
BOUNDARIES = [1e4, 2.5e4, 5e4, 1e5, 2.5e5, 5e5, 1e6, 2.5e6, 5e6]
N_BUCKETS = len(BOUNDARIES) + 1  # 10

REPORTING_THRESHOLD = 1_000_000.0  # ₹10 lakh
PROXIMITY_BAND = 0.10  # within 10% of the threshold


def amount_bucket(amount: float) -> str:
    """Map an amount to ``bucket_1`` (≤ ₹10K) … ``bucket_10`` (> ₹50L). Fixed boundaries.

    ``bisect_left`` gives ``≤`` semantics: a boundary value lands in the
    lower bucket (e.g. exactly ₹10K → bucket_1, exactly ₹25K → bucket_2).
    """
    return f"bucket_{bisect.bisect_left(BOUNDARIES, float(amount)) + 1}"


# Representative amount per bucket, used where a scalar proxy is needed *after* pseudonymisation
# (graph-engine flow-conservation + GraphSAGE scoring). These are geometric midpoints of
# each band; the open top bucket uses 1.5x its lower edge. This never recovers a real amount — it
# is a fixed, shared stand-in so cross-institution flow ratios stay comparable.
_MIDPOINTS = [5e3]  # bucket_1: <= 10K
_MIDPOINTS += [(BOUNDARIES[i - 1] * BOUNDARIES[i]) ** 0.5 for i in range(1, len(BOUNDARIES))]
_MIDPOINTS += [BOUNDARIES[-1] * 1.5]  # bucket_10: > 50L, open-ended


def bucket_midpoint(bucket: str) -> float:
    """Representative amount for a fixed bucket label (``bucket_1`` … ``bucket_10``)."""
    idx = int(bucket.split("_")[1]) - 1
    return float(_MIDPOINTS[idx])


def threshold_proximity(amount: float) -> str:
    """``high`` if within 10% of the ₹10 lakh reporting threshold, else ``low``."""
    return (
        "high"
        if abs(float(amount) - REPORTING_THRESHOLD) <= PROXIMITY_BAND * REPORTING_THRESHOLD
        else "low"
    )
