# ACN — AML Consortium Network

A privacy-preserving system in which five financial institutions collaboratively detect
**cross-institution transaction layering** without sharing raw transaction data. Each bank
publishes only **pseudonymised** transaction edges (HMAC-hashed accounts, fixed amount buckets);
these merge into one shared graph where the *same real account collapses to a single node* —
regardless of which bank reported it — making cross-bank laundering chains visible that no single
institution could see. The output is a stream of **ranked, explainable alerts** — each with its
evidence subgraph — routed only to the institutions involved.

## How it works

1. **Data foundation** — sample the IBM AML dataset, preserving whole laundering chains, and
   partition banks into five non-IID institutions.
2. **Pseudonymisation** — each bank hashes its accounts (ownership-based HMAC-SHA256), buckets
   amounts, and publishes only pseudonymised edges to Kafka (mTLS).
3. **Graph engine** — Neo4j ingests the edges into one merged graph; six Cypher detection layers
   surface layering patterns matching the AMLSim topologies (sliding-window, 30-day path tracker,
   round-trip, flow-conservation, coordinated new accounts, fan-out/scatter).
4. **Scoring** — a GraphSAGE model (trained on the pseudonymised merged graph) scores each account;
   the Cypher layers' path findings are fed in as a **chain-aware feature block**, so the 2-hop
   model can key off the long-range chain structure its receptive field can't reach. A candidate's
   alert score is the max laundering probability over its evidence accounts.
5. **Explainability** — GNNExplainer turns each alert into a plain-language evidence string.
6. **Alerting** — alerts are routed only to the involved institutions, with the evidence subgraph
   written atomically.
7. **Case management** — alerts become investigation cases; each bank resolves *only its own*
   accounts (owner-side hash resolution) and gets a draft STR (template + optional local LLM) with
   a mandatory human-review gate. Nothing is ever filed automatically. `GET/POST /cases` API.

Everything runs locally on a Mac (Docker Compose for the services).

## Repository layout

```
acn/            Reusable Python, one sub-package per domain:
                data/ pseudonymise/ gnn/ graph/ explain/ casemgmt/
services/       api/ = FastAPI /health + /cases.
frontend/       Next.js compliance console (alert queue, case detail, officer decisions).
scripts/        Data build, model training, resolve-map build, cert gen, runners.
tests/          pytest — deterministic units + gated `requires_services` integration.
config/         redis.conf, Kafka client-ssl template.
certs/          mTLS material (generated, gitignored).
```

## Compliance console (UI)

A Next.js dashboard over the `/cases` API — alert queue, case detail with owner-resolved evidence
and an editable draft STR, and file/dismiss/escalate decisions.

```bash
cd frontend && npm install && npm run dev   # http://localhost:3000 (API on :8000)
```

## Status

**Complete and running end-to-end** on the full dataset: data → pseudonymise → graph → detection
layers → GraphSAGE with chain-aware features → GNNExplainer → targeted alerts → case management +
draft STR, with a Next.js compliance UI. Detection holds ~0.64 recall@5%FPR / 0.89 AUC (multi-seed).
**Roadmap:** quantify the consortium lift (per-bank-alone vs. merged recall).

## Requirements

- Docker + Docker Compose, Python 3.11
- Two dependency sets, kept apart on purpose:
  - `requirements.txt` — the light **local-services** runtime (API, DB/bus clients, tests)
  - `requirements-ml.txt` — the **ML** stack (torch / torch-geometric / scikit-learn) for
    training + scoring

## Getting started (local services)

```bash
cp .env.example .env            # fill NEO4J_PASSWORD, ACN_SHARED_SALT, etc. (never commit)
bash scripts/gen_certs.sh       # generate the mTLS CA + broker/admin/institution certs
docker compose up -d            # Kafka (mTLS), Neo4j, Redis (AOF), FastAPI, Ollama
# wait ~30s (Neo4j is the long pole), then:
bash scripts/create-topics.sh   # 7 Kafka topics (edges_INST_A..E, count_commitments, alerts)
bash scripts/set-acls.sh        # per-institution write-own ACLs; server read/alerts-write
docker compose exec -T neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" < scripts/neo4j_schema.cypher
curl -s http://localhost:8000/health | jq   # every core dependency should be "ok"
```


## Building the pipeline (with the LI-Medium dataset local)

```bash
python scripts/build_dataset.py       # sample + partition the 31M-row dataset (chain-preserving)
ACN_SHARED_SALT=... python scripts/replay_producer.py --splits-dir acn-data/data/splits/detect …
python scripts/run_graph_engine.py --phase ingest    # Kafka -> Neo4j
python scripts/train_gnn.py           # GraphSAGE (+ chain features) on the merged graph -> checkpoint
python scripts/run_graph_engine.py --phase detect --checkpoint acn-data/models/gnn/graphsage_final.pt
python scripts/run_graph_engine.py --phase explain   # GNNExplainer evidence on the alerts
```

## Development

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
ruff check . && black --check .
pytest -m "not requires_services"     # deterministic tests (no stack needed)
pytest -m requires_services           # integration tests (stack must be up)
```

## Non-negotiable invariants

Raw transaction data never leaves an institution; only **pseudonymised edges** cross a boundary
(used both to build the shared merged graph and to detect on it). No raw identity, exact amount,
or salt ever reaches Neo4j, Kafka, logs, or the UI. Accounts are hashed with HMAC-SHA256 keyed on
the **owning** institution's id. The model trains on the pseudonymised merged graph only — never
on raw data pooled centrally. Alerts are routed only to the institutions whose accounts appear in
the evidence — never broadcast.
