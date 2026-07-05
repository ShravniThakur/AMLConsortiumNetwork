"""Chain-aware feature tests (pure — the Cypher `compute` is exercised via requires_services).

Covers the label-free aggregation shape/contract: the matrix aligns to node order, uncovered
accounts get an all-zero row (bottom of the distribution), and `append` widens the base matrix by
exactly the chain block.
"""

from __future__ import annotations

import numpy as np

from acn.graph import chain_features


def test_feature_contract():
    # 4 shape scalars + one flag per pattern; append-only order.
    assert chain_features.N_CHAIN_FEATURES == 4 + len(chain_features.PATTERNS)
    assert chain_features.FEATURE_NAMES[0] == "chain_count"
    assert chain_features.FEATURE_NAMES[-1] == "in_fan_out"


def _row(chain_count: float) -> list[float]:
    """A well-formed chain-feature row of the current width (chain_count in col 0)."""
    return [chain_count] + [0.0] * (chain_features.N_CHAIN_FEATURES - 1)


def test_matrix_aligns_and_zero_fills():
    nodes = ["a", "b", "c"]
    chain = {"a": _row(2), "c": _row(1)}
    m = chain_features.matrix(nodes, chain)
    assert m.shape == (3, chain_features.N_CHAIN_FEATURES)
    assert np.array_equal(m[0], chain["a"])  # covered node keeps its row
    assert np.array_equal(m[1], np.zeros(chain_features.N_CHAIN_FEATURES))  # uncovered → zeros
    assert m[2, 0] == 1  # c's chain_count


def test_append_widens_by_chain_block():
    nodes = ["a", "b"]
    base = np.ones((2, 21))
    out = chain_features.append(nodes, base, {"a": _row(1)})
    assert out.shape == (2, 21 + chain_features.N_CHAIN_FEATURES)
    assert np.array_equal(out[:, :21], base)  # base columns untouched
    assert out[1, 21:].sum() == 0  # uncovered node's chain block is zeros
