"""Canonical column names for the data-foundation pipeline.

The raw IBM AML LI-Medium CSVs use spaced, title-cased headers (``From Bank``,
``Is Laundering`` …). Everything downstream works in snake_case, so `load.py`
normalises once at the boundary and the rest of the pipeline speaks these names.
Keep this in sync with the data model.
"""

from __future__ import annotations

# Raw transaction header -> canonical name. The raw account columns are positional in
# the IBM files (a second "Account" header); `load.py` handles that quirk explicitly.
RAW_TO_CANONICAL = {
    "Timestamp": "timestamp",
    "From Bank": "from_bank",
    "From Account": "from_account",
    "To Bank": "to_bank",
    "To Account": "to_account",
    "Amount Received": "amount_received",
    "Receiving Currency": "receiving_currency",
    "Amount Paid": "amount_paid",
    "Payment Currency": "payment_currency",
    "Payment Format": "payment_format",
    "Is Laundering": "is_laundering",
}

# Columns present after join + label (before clustering/partitioning adds institutions).
JOINED_COLUMNS = [
    "timestamp",
    "from_bank",
    "from_account",
    "to_bank",
    "to_account",
    "amount_paid",
    "amount_received",
    "payment_currency",
    "receiving_currency",
    "payment_format",
    "is_laundering",
    "from_bank_name",
    "to_bank_name",
]

# The five institution labels, in order.
INSTITUTIONS = ["INST_A", "INST_B", "INST_C", "INST_D", "INST_E"]

# Window boundary: train = Sep 1–10 2022, detect = Sep 11–16 2022 (inclusive).
TRAIN_END = "2022-09-10"  # last day in the training window
DETECT_START = "2022-09-11"  # first day in the detection window
DETECT_END = "2022-09-16"  # last day in the detection window
