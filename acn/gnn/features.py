"""Shared GNN feature constants.

The canonical list of node feature columns and amount-bucket dimensions used by
the GraphSAGE model at both training time (train_gnn.py) and inference time
(graph/score.py). All consumers import from here to stay in sync — if you add a
feature column, add it here and nowhere else.

Training and inference both reconstruct features from pseudonymised data
(bucket midpoints, not raw amounts), so these constants describe the same
representation in both phases.
"""

from __future__ import annotations

# Fixed amount-bucket boundaries (₹10K → ₹50L). 10 buckets total.
BUCKET_BOUNDARIES = [1e4, 2.5e4, 5e4, 1e5, 2.5e5, 5e5, 1e6, 2.5e6, 5e6]
N_BUCKETS = len(BUCKET_BOUNDARIES) + 1  # 10

# Scalar feature columns in fixed order (the model consumes this matrix).
# Append-only — changing order or removing a column breaks saved checkpoints.
SCALAR_FEATURES = [
    "is_boundary",
    "txn_count",
    "amount_mean",
    "amount_std",
    "age_days",
    "velocity_per_day",
    "new_counterparty_ratio",
    "total_in",
    "flow_ratio",
    "in_degree",
    "out_degree",
]

# Edge features for DirMultigraphSAGE — one vector per directed edge.
# Built from the pseudonymised fields already on each SENT relationship in Neo4j:
#   amount_bucket → midpoint (log-normalised)
#   threshold_proximity → binary structuring flag
#   timestamp → days from window start (captures timing patterns across parallel edges)
#   bucket_onehot (10 dims) → categorical treatment of the amount bucket
# Append-only — changing order breaks saved multigraph checkpoints.
EDGE_FEATURE_NAMES = [
    "edge_bucket_midpoint",  # log1p(midpoint) / 16.0 — normalised log-amount proxy
    "edge_near_threshold",  # 1.0 if threshold_proximity == "high" else 0.0
    "edge_time_delta_days",  # (ts - window_start) / 365.0 — position in the window
    "edge_time_since_prev_days",  # (ts - prev_ts) / 1.0 days — burst velocity
    "edge_is_night",  # 1.0 if UTC hour < 6 or > 22
    "edge_is_weekend",  # 1.0 if Saturday/Sunday
    "edge_is_round_amount",  # 1.0 if raw amount % 10000 == 0
    # One-hot: which of the 10 fixed amount buckets does this edge belong to?
    "edge_bucket_1",
    "edge_bucket_2",
    "edge_bucket_3",
    "edge_bucket_4",
    "edge_bucket_5",
    "edge_bucket_6",
    "edge_bucket_7",
    "edge_bucket_8",
    "edge_bucket_9",
    "edge_bucket_10",
]
N_EDGE_FEATURES = len(EDGE_FEATURE_NAMES)  # 17
