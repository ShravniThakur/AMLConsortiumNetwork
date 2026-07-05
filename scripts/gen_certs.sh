#!/usr/bin/env bash
# ACN mTLS material generator.
#
# Produces, under ./certs/kafka/:
#   ca-cert.pem / ca-key.pem                     — the one CA that signs everything
#   kafka.broker.keystore.jks / .truststore.jks  — broker identity + trusted CA (JKS)
#   kafka.admin.keystore.jks                      — CLI super-user (topics + ACLs)
#   INST_X-cert.pem / INST_X-key.pem              — per-institution PEM for confluent-kafka
#   *_creds                                       — JKS credential files read by the broker
#
# The point: the broker authenticates clients by cert, and ACLs bind
# each client cert's CN (CN=INST_A -> User:INST_A) to its own topic. A plaintext client is
# refused. Private keys / JKS / creds are gitignored — never commit them.
#
# Requires: openssl and keytool (JDK). Idempotent-ish: it recreates the certs/kafka dir.
set -euo pipefail

CERT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/certs/kafka"
VALIDITY_DAYS="${CERT_VALIDITY_DAYS:-3650}"
# Store passwords: override via env in a real setup; these must match client-ssl.properties.
# PKCS12 keystores require the key password to equal the store password — keep them one value.
STORE_PASS="${KAFKA_STORE_PASS:-acn-dev-store}"
KEY_PASS="${KAFKA_KEY_PASS:-$STORE_PASS}"
# Modern keytool (JDK 9+) defaults to PKCS12; be explicit so the broker's declared
# KAFKA_SSL_*_TYPE=PKCS12 matches the actual store format.
STORETYPE=PKCS12
INSTITUTIONS=(INST_A INST_B INST_C INST_D INST_E)

echo "==> Generating mTLS material in ${CERT_DIR}"
rm -rf "${CERT_DIR}"
mkdir -p "${CERT_DIR}"
cd "${CERT_DIR}"

# 1. Certificate Authority ----------------------------------------------------
openssl req -new -x509 -keyout ca-key.pem -out ca-cert.pem \
  -days "${VALIDITY_DAYS}" -nodes -subj "/CN=ACN-CA/O=ACN"

# Credential files the broker reads (KAFKA_SSL_*_CREDENTIALS).
printf '%s' "${STORE_PASS}" > broker_keystore_creds
printf '%s' "${STORE_PASS}" > broker_truststore_creds
printf '%s' "${KEY_PASS}"   > broker_key_creds

# Truststore trusts the CA (shared by broker + all clients).
keytool -keystore kafka.broker.truststore.jks -alias CARoot \
  -import -file ca-cert.pem -storepass "${STORE_PASS}" -storetype "${STORETYPE}" -noprompt

# 2. A signed JKS identity for a given CN --------------------------------------
# make_jks_identity <cn> <keystore-file>
make_jks_identity() {
  local cn="$1" ks="$2"
  keytool -keystore "${ks}" -alias "${cn}" -validity "${VALIDITY_DAYS}" \
    -genkey -keyalg RSA -storetype "${STORETYPE}" \
    -storepass "${STORE_PASS}" -keypass "${KEY_PASS}" \
    -dname "CN=${cn},O=ACN"
  keytool -keystore "${ks}" -alias "${cn}" -certreq -file "${cn}.csr" \
    -storepass "${STORE_PASS}"
  openssl x509 -req -CA ca-cert.pem -CAkey ca-key.pem -in "${cn}.csr" \
    -out "${cn}-signed.pem" -days "${VALIDITY_DAYS}" -CAcreateserial
  keytool -keystore "${ks}" -alias CARoot -import -file ca-cert.pem \
    -storepass "${STORE_PASS}" -storetype "${STORETYPE}" -noprompt
  keytool -keystore "${ks}" -alias "${cn}" -import -file "${cn}-signed.pem" \
    -storepass "${STORE_PASS}" -noprompt
  rm -f "${cn}.csr" "${cn}-signed.pem"
}

echo "==> Broker keystore"
make_jks_identity "kafka" "kafka.broker.keystore.jks"

echo "==> Admin (super-user) keystore for topic + ACL management"
make_jks_identity "admin" "kafka.admin.keystore.jks"

# 3. Per-institution PEM identities (confluent-kafka python uses PEM) -----------
for inst in "${INSTITUTIONS[@]}"; do
  echo "==> Institution cert: ${inst}"
  openssl req -new -newkey rsa:2048 -nodes \
    -keyout "${inst}-key.pem" -out "${inst}.csr" -subj "/CN=${inst}/O=ACN"
  openssl x509 -req -CA ca-cert.pem -CAkey ca-key.pem -in "${inst}.csr" \
    -out "${inst}-cert.pem" -days "${VALIDITY_DAYS}" -CAcreateserial
  rm -f "${inst}.csr"
done

# 4. Server (consumer) PEM identity — principal User:server has the read ACLs --
echo "==> Server (graph-engine consumer) cert"
openssl req -new -newkey rsa:2048 -nodes \
  -keyout "server-key.pem" -out "server.csr" -subj "/CN=server/O=ACN"
openssl x509 -req -CA ca-cert.pem -CAkey ca-key.pem -in "server.csr" \
  -out "server-cert.pem" -days "${VALIDITY_DAYS}" -CAcreateserial
rm -f "server.csr"

# 5. Admin CLI client config (used by create-topics.sh / set-acls.sh) ----------
# The Kafka CLI runs inside the broker container with --command-config pointing here
# (/etc/kafka/secrets/client-ssl.properties). Generate it now, filled with the real
# store passwords, so those scripts work without a manual copy-and-edit of the template.
echo "==> Admin client config (client-ssl.properties)"
cat > client-ssl.properties <<EOF
security.protocol=SSL
ssl.truststore.location=/etc/kafka/secrets/kafka.broker.truststore.jks
ssl.truststore.password=${STORE_PASS}
ssl.keystore.location=/etc/kafka/secrets/kafka.admin.keystore.jks
ssl.keystore.password=${STORE_PASS}
ssl.key.password=${KEY_PASS}
# Broker cert has no matching hostname in dev — disable endpoint identification locally.
ssl.endpoint.identification.algorithm=
EOF

echo "==> Done. CN maps to the Kafka principal (CN=INST_A -> User:INST_A) via the"
echo "    broker's KAFKA_SSL_PRINCIPAL_MAPPING_RULES. Next: create-topics.sh, set-acls.sh."
