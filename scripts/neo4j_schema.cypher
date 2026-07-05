// ACN Neo4j schema.
// The UNIQUE constraint on Account.hash is what makes ownership-based hashing
// collapse to exactly one node per real account — without it, replays and multiple
// publishers create duplicate :Account nodes and graph connectivity breaks.

CREATE CONSTRAINT account_hash IF NOT EXISTS
  FOR (a:Account) REQUIRE a.hash IS UNIQUE;

// Idempotent edge writes depend on a unique event_id per :SENT relationship
// (MERGE on event_id "idempotent edge write").
CREATE CONSTRAINT sent_event_id IF NOT EXISTS
  FOR ()-[r:SENT]-() REQUIRE r.event_id IS UNIQUE;

// Windowed detection queries must be bounded by timestamp and use this index —
// never scan the full graph.
CREATE INDEX sent_timestamp IF NOT EXISTS
  FOR ()-[r:SENT]-() ON (r.timestamp);

// Account age / Layer-5 coordinated-new-account features read first_seen_ts.
CREATE INDEX account_first_seen IF NOT EXISTS
  FOR (a:Account) ON (a.first_seen_ts);

// Alerts are MERGEd on a deterministic alert_id so re-running detection over the same
// window/evidence is idempotent (one :Alert, not a duplicate per replay).
CREATE CONSTRAINT alert_id IF NOT EXISTS
  FOR (a:Alert) REQUIRE a.alert_id IS UNIQUE;
