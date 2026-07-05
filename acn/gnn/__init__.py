"""GraphSAGE laundering detector + graph/feature construction + eval metrics.

The model trains on the pseudonymised merged graph — privacy comes from pseudonymisation (the
merged graph holds only hashes + buckets, no raw identity/amount leaves a bank)."""
