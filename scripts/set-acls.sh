#!/usr/bin/env bash
# Set ACN Kafka ACLs.
#
# The privacy property of the transport: each institution principal may WRITE only its
# own edges_INST_X topic (and count_commitments); the server principal READS the edge
# topics and WRITES alerts. No institution can read another's topic. The setup
# cross-topic-write test deliberately fails against these ACLs.
set -euo pipefail

BOOTSTRAP="${KAFKA_BOOTSTRAP:-kafka:9093}"
CLIENT_CONFIG="${KAFKA_CLIENT_CONFIG:-/etc/kafka/secrets/client-ssl.properties}"
SERVER_PRINCIPAL="${ACN_SERVER_PRINCIPAL:-User:server}"
INSTITUTIONS=(INST_A INST_B INST_C INST_D INST_E)

run_acls() {
  docker compose exec -T kafka kafka-acls --bootstrap-server "${BOOTSTRAP}" \
    --command-config "${CLIENT_CONFIG}" "$@"
}

for inst in "${INSTITUTIONS[@]}"; do
  echo "==> ${inst}: WRITE only edges_${inst} + count_commitments"
  run_acls --add --allow-principal "User:${inst}" \
    --operation Write --operation Describe --topic "edges_${inst}"
  run_acls --add --allow-principal "User:${inst}" \
    --operation Write --operation Describe --topic count_commitments
done

echo "==> Server principal (${SERVER_PRINCIPAL}): READ all edge topics + WRITE alerts"
for inst in "${INSTITUTIONS[@]}"; do
  run_acls --add --allow-principal "${SERVER_PRINCIPAL}" \
    --operation Read --operation Describe --topic "edges_${inst}"
done
run_acls --add --allow-principal "${SERVER_PRINCIPAL}" \
  --operation Read --operation Describe --topic count_commitments
run_acls --add --allow-principal "${SERVER_PRINCIPAL}" \
  --operation Write --operation Describe --topic alerts
# Consumer group for the graph engine.
run_acls --add --allow-principal "${SERVER_PRINCIPAL}" \
  --operation Read --group "acn-graph-engine"

echo "==> Current ACLs:"
run_acls --list
