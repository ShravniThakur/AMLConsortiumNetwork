"""Train/detect window split.

Train on Sep 1–10 2022; detect on Sep 11–16 2022. The detect window's laundering
chains are the held-out positives used for evaluation. The split is on
``timestamp`` with a hard boundary and a no-overlap guard.
"""

from __future__ import annotations

import pandas as pd

from .schema import DETECT_END, DETECT_START


def split_train_detect(
    df: pd.DataFrame,
    detect_start: str = DETECT_START,
    detect_end: str = DETECT_END,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (train, detect): train = timestamp before detect_start; detect = the window.

    Detect is ``[detect_start, detect_end]`` with ``detect_end`` inclusive of the whole
    day. Rows after ``detect_end`` (none in LI-Medium, which ends Sep 16) fall in neither.
    """
    ts = pd.to_datetime(df["timestamp"])
    boundary = pd.Timestamp(detect_start)
    detect_upper = pd.Timestamp(detect_end) + pd.Timedelta(days=1)  # exclusive upper

    train = df[ts < boundary]
    detect = df[(ts >= boundary) & (ts < detect_upper)]

    # No-overlap invariant: a row cannot be in both windows.
    assert set(train.index).isdisjoint(set(detect.index)), "train/detect windows overlap"
    return train.reset_index(drop=True), detect.reset_index(drop=True)
