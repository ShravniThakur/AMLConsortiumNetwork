#!/usr/bin/env bash
# Create the 7 ACN Kafka topics.
#   edges_INST_A..E  — one per institution, pseudonymised edges only (raw never on Kafka)
#   count_commitments — per-window SHA-256 count commitments
#   alerts            — targeted alert portions from the graph engine
#
# Runs the CLI as the admin super-user over the mTLS listener. Auto-topic-creation is
# disabled on the broker, so these must exist before any producer runs.
set -euo pipefail

BOOTSTRAP="${KAFKA_BOOTSTRAP:-kafka:9093}"
# Client config authenticating as admin (copy config/kafka/client-ssl.properties.example
# to certs/kafka/client-ssl.properties and fill the store passwords from gen_certs.sh).
CLIENT_CONFIG="${KAFKA_CLIENT_CONFIG:-/etc/kafka/secrets/client-ssl.properties}"
PARTITIONS="${KAFKA_TOPIC_PARTITIONS:-3}"
REPLICATION="${KAFKA_TOPIC_REPLICATION:-1}"

TOPICS=(
  edges_INST_A edges_INST_B edges_INST_C edges_INST_D edges_INST_E
  count_commitments
  alerts
)

# Run kafka-topics inside the broker container so the CLI + certs are present.
run_topics() {
  docker compose exec -T kafka kafka-topics --bootstrap-server "${BOOTSTRAP}" \
    --command-config "${CLIENT_CONFIG}" "$@"
}

for topic in "${TOPICS[@]}"; do
  echo "==> Creating topic ${topic}"
  run_topics --create --if-not-exists --topic "${topic}" \
    --partitions "${PARTITIONS}" --replication-factor "${REPLICATION}"
done

echo "==> Topics present:"
run_topics --list
