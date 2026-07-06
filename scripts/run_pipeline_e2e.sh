#!/bin/bash
set -e

echo "Starting E2E Pipeline..."

# 1. Replay edges to Kafka
ACN_SHARED_SALT="test_salt" python scripts/replay_producer.py --splits-dir acn-data/data/splits/detect

# 2. Ingest edges from Kafka to Neo4j
python scripts/run_graph_engine.py --phase ingest

# 3. Detect anomalies using Cypher + GraphSAGE
python scripts/run_graph_engine.py --phase detect --checkpoint acn-data/models/gnn/graphsage_final.pt

# 4. Generate explainable evidence for alerts
python scripts/run_graph_engine.py --phase explain

echo "Pipeline completed successfully."
