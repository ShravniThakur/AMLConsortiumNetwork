"""Evaluation metrics for the detector.

``recall@5%FPR`` is the cross-baseline comparison / convergence-gate metric (— the
*deployed* operating threshold is calibrated separately). Pure numpy/sklearn, so
this is unit-tested locally the training runs locally too.
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import roc_auc_score, roc_curve


def recall_at_fpr(y_true, scores, fpr: float = 0.05) -> float:
    """Recall (TPR) at the operating point whose false-positive rate is ≤ ``fpr``.

    Finds the largest threshold whose FPR does not exceed ``fpr`` and returns the TPR there.
    Needs both classes present; returns 0.0 if there are no positives.
    """
    y_true = np.asarray(y_true).astype(int)
    scores = np.asarray(scores, dtype=float)
    if y_true.sum() == 0 or y_true.sum() == len(y_true):
        return 0.0
    fprs, tprs, _ = roc_curve(y_true, scores)
    ok = np.where(fprs <= fpr)[0]
    return float(tprs[ok[-1]]) if len(ok) else 0.0


def auc_roc(y_true, scores) -> float:
    """AUC-ROC; returns 0.5 (chance) if only one class is present."""
    y_true = np.asarray(y_true).astype(int)
    if y_true.sum() == 0 or y_true.sum() == len(y_true):
        return 0.5
    return float(roc_auc_score(y_true, np.asarray(scores, dtype=float)))
