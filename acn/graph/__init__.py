"""Graph: NetworkX builders + node features, Neo4j writers and Cypher detection layers.

Holds only pseudonymised data on the Neo4j side (hashes, amount buckets, proximity flags).
Writes are idempotent via MERGE on event_id / Account.hash.
"""
