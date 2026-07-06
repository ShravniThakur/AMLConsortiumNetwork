# ACN — End-to-End Testing Runbook

Run the whole system from scratch and watch it work: Docker stack → data → pipeline →
alerts → compliance console UI. Follow the steps **in order**. Each step has a
**✅ Check** so you know it worked before moving on.

Expect ~**20–30 min** end to end (most of it is the one-time data build + model training).

---

## 0. Prerequisites (do these once)

| Need | Why | How |
|---|---|---|
| **Docker + Docker Compose** | the service stack (Kafka/Neo4j/Redis/API/Ollama) | Docker Desktop |
| **Python 3.11** | the pipeline scripts | `python3.11 --version` — if missing, see Step 5 (conda/brew) |
| **Node 18+** | the Next.js UI | `node --version` |
| **~16 GB RAM free** | Neo4j + Kafka + Ollama are heavy | close other apps |
| **The LI-Medium dataset** | the raw transactions the pipeline builds from | see below ⬇️ |

### Download the dataset (required — the pipeline can't run without it)
Get **IBM Transactions for Anti-Money Laundering (AML)**, the **LI-Medium** files, from Kaggle:
<https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml>

Put these two files here (create the folder if needed):

```
acn-data/data/raw/LI-Medium_Trans.csv        # ~2.9 GB — the transactions
acn-data/data/raw/LI-Medium_accounts.csv     # ~140 MB — the accounts
```

> The transactions file may be named `LI-Medium_Trans-002.csv` etc. — any `*Trans*.csv`
> in that folder is auto-detected. Don't commit these; `acn-data/` is gitignored.

---

## 1. Clean slate

If you've run any stack before (containers named `acn-*` or `ffcdn-*`), stop it so ports
7687 / 9093 / 8000 are free:

```bash
docker compose down -v          # from the project root; -v wipes old volumes for a true fresh start
docker ps -a | grep -E 'acn-'   # should be empty
```

**✅ Check:** no ACN/ffcdn containers running.

---

## 2. Configure secrets (`.env`)

```bash
cp .env.example .env
```

Open `.env` and fill (the rest can stay as-is):

```
ACN_SHARED_SALT=<any long random string>          # the HMAC salt — keep it stable across the run
NEO4J_PASSWORD=<any password>
```

> ⚠️ `.env` holds secrets and is gitignored — never commit it.

---

## 3. (Recommended) Give Neo4j more heap

Training loads the whole 600k-edge graph plus runs 6 Cypher layers. The default heap (1 GB)
can OOM-kill Neo4j mid-pipeline. Bump it **before** starting the stack — in `docker-compose.yml`,
under the `neo4j:` service, change:

```yaml
      NEO4J_server_memory_heap_max__size: 2G      # was 1G
      NEO4J_server_memory_pagecache_size: 1G      # was 512m
```

(If you skip this and Neo4j dies during Step 7/8, just `docker compose restart neo4j` and re-run
that step — the graph persists in its volume.)

---

## 4. Certificates + bring up the stack

```bash
bash scripts/gen_certs.sh          # generates the mTLS CA + broker/admin/institution/server certs
docker compose up -d               # Kafka (mTLS), Neo4j, Redis, FastAPI api, Ollama
sleep 60                           # Neo4j is the long pole
```

Then create the Kafka topics, set the ACLs, and load the Neo4j schema:

```bash
bash scripts/create-topics.sh      # 7 topics: edges_INST_A..E, count_commitments, alerts
bash scripts/set-acls.sh           # per-institution write-own ACLs + server read/alerts-write
docker compose exec -T neo4j cypher-shell -u neo4j -p "$(grep '^NEO4J_PASSWORD' .env | cut -d= -f2)" \
  < scripts/neo4j_schema.cypher    # constraints + indexes
```

**✅ Check:**

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

You should see `"status": "ok"` with `neo4j`, `redis`, `kafka` all `"ok"`
(`ollama: unloaded` is normal — the model loads on demand).

---

## 5. Python environment


> **No `python3.11`?** It isn't the system default on most Macs. Get a 3.11 interpreter first:
> - **conda (if you have Anaconda/Miniconda):** `conda create -y -n acn python=3.11 && conda activate acn`
>   — then **skip the `venv` line below** and just run the `pip install`s inside this env.
> - **Homebrew:** `brew install python@3.11` — then use `python3.11 -m venv .venv` as written.
>
> 3.11 is the tested version; 3.13 may hit wheel-availability issues with torch-geometric.

```bash
python3.11 -m venv .venv          # (skip this line if you used the conda env above)
source .venv/bin/activate         # (skip too — conda activate already did it)
pip install -r requirements.txt          # light runtime + tools
pip install -e .                         # the `acn` package (editable)
pip install -r requirements-ml.txt       # sklearn / numpy / pandas / networkx / pyarrow
pip install "torch>=2.2" "torch-geometric>=2.5"   # the GNN stack (kept out of requirements-ml on purpose)
```

**✅ Check:**

```bash
python -c "import torch, torch_geometric, acn; print('ok', torch.__version__)"
python -m pytest -m "not requires_services" -q      # 65 pass, 8 skip (Neo4j requires env from Step 6)
```

---

## 6. Set the pipeline environment (host → localhost)

The scripts below run **on your Mac** and talk to the containers on `localhost`. Run this once
per terminal session (it loads `.env`, then overrides the in-container addresses):

```bash
set -a; source .env; set +a
export NEO4J_URI="bolt://localhost:7687"
export REDIS_URL="redis://localhost:6379/0"
export KAFKA_BROKER="localhost:9093"
export KAFKA_SSL_CAFILE="certs/kafka/ca-cert.pem"
export KAFKA_SSL_CERTFILE="certs/kafka/server-cert.pem"     # the graph engine acts as the "server" principal
export KAFKA_SSL_KEYFILE="certs/kafka/server-key.pem"
export PYTHONPATH="$PWD"
```

---

## 7. Build the data foundation

```bash
python scripts/build_dataset.py --seed 42
```

This streams the 31M-row dataset, chain-preservingly samples it, and partitions into 5
non-IID institutions. **Takes a few minutes.**

**✅ Check:** you should see a summary like `TRAIN : 250,000 rows … DETECT: 600,000 rows …`,
and these appear:

```
acn-data/data/splits/detect/INST_A.parquet … INST_E.parquet
acn-data/data/splits/train/INST_A.parquet  … INST_E.parquet
```

---

## 8. Run the detection pipeline

Run these **in order** (same terminal, env from Step 6 still set):

```bash
# 8a. Each bank pseudonymises its edges and publishes them to Kafka over mTLS
python scripts/replay_producer.py --splits-dir acn-data/data/splits/detect \
       --certs-dir certs/kafka --broker localhost:9093
#   ✅ "total edges published: 600000"

# 8b. The graph engine (server principal) consumes Kafka → merges into Neo4j
python scripts/run_graph_engine.py --phase ingest
#   ✅ "[ingest] graph now: {'accounts': ~601879, 'sent_edges': 600000}"

# 8c. Train DirMultigraphSAGE (+ the chain-aware feature block) on the merged graph
python scripts/train_gnn.py --seed 42 --epochs 300 --lr 0.005
#   ✅ "[gnn] trained 300 epochs … held-out AUC ~0.84+ | recall@5%FPR ~0.60+"
#      → writes acn-data/models/gnn/multigraph_final.pt

# 8d. Detect: run the 6 Cypher layers, score with DirMultigraphSAGE, raise targeted alerts
python scripts/run_graph_engine.py --phase detect \
       --checkpoint acn-data/models/gnn/multigraph_final.pt
#   ✅ "[detect] raised ~1800 targeted alerts"

# 8e. Explain: attach a plain-language GNNExplainer evidence string to the top alerts
python scripts/run_graph_engine.py --phase explain \
       --checkpoint acn-data/models/gnn/multigraph_final.pt
#   ✅ "[explain] attached evidence to 50 alerts"
```

> **If Neo4j dies** during 8c/8d (`ServiceUnavailable` / connection refused): it OOM'd.
> `docker compose restart neo4j`, wait ~20s, and re-run that one step. (Do Step 3's heap bump to
> avoid it.)

### 8f. Build the owner-side resolution map (so the UI can un-hash a bank's own accounts)

```bash
python scripts/build_resolve_map.py --splits-dir acn-data/data/splits/detect
#   ✅ writes resolve:{INST} hashes into Redis
```

**✅ Check the API sees alerts:**

```bash
curl -s "http://localhost:8000/cases?limit=3" | python3 -m json.tool
```

You should get a list of cases (alerts) with `pattern`, `score`, `institutions`.

---

## 9. The compliance console (UI)

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000  (it calls the API on :8000)
```

Open **<http://localhost:3000>** and walk through it:

1. **Alert queue** (home) — cross-institution alerts, worst score first. Filter by status.
2. **Click an alert** → case detail:
   - **"Viewing as"** — pick an institution; only *that* bank's own accounts get un-hashed
     (others stay pseudonymised — the privacy point).
   - **Why it was flagged** — the GNNExplainer evidence string.
   - **Draft STR** — editable machine draft (template by default; LLM if you pulled the Ollama model).
   - Enter an officer name and click **File / Escalate / Dismiss** — the decision is recorded.

**✅ Check:** you can open a case, switch "viewing as" and see one bank's accounts resolve while
others stay hashed, and record a decision that sticks after refresh.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `/health` shows a dep down | give it more time (Neo4j ~60s); `docker compose logs neo4j` |
| Neo4j `ServiceUnavailable` mid-pipeline | OOM — do Step 3 (heap bump), `docker compose restart neo4j`, re-run the step |
| create-topics/set-acls: `NoSuchFileException: /etc/kafka/secrets/client-ssl.properties` | your certs predate the fix that auto-writes it — re-run `bash scripts/gen_certs.sh`, then `docker compose restart kafka` (broker must reload the regenerated CA) |
| `GROUP_AUTHORIZATION_FAILED` on ingest | re-run `bash scripts/set-acls.sh` (grants the server principal on group `acn-graph-engine`) |
| ingest reads 0 messages | run 8a (replay) before 8b (ingest); confirm topics exist: `bash scripts/create-topics.sh` |
| `/cases` is empty | you haven't run 8d (detect) yet, or it raised 0 alerts |
| UI accounts all show as hashes | run 8f (`build_resolve_map.py`), then pick a bank in "Viewing as" |
| Draft STR looks templated, not LLM | expected unless you `docker compose exec ollama ollama pull llama3.1:8b` and pass `?use_llm=true` |
| port already in use | an old stack is up — Step 1 (`docker compose down -v`) |

## What "working" looks like end-to-end
data build → 600k edges on Kafka → merged graph in Neo4j (~601k accounts) → a trained
DirMultigraphSAGE checkpoint → ~1,800 targeted alerts → a browsable queue where each case
resolves only its owning bank's accounts, carries plain-language evidence, drafts an STR, and
records officer decisions.

---

## 9. Measure the Consortium Lift

To quantify exactly *why* the consortium exists, run the lift measurement script. This simulates each bank running detection strictly on its own local edges, versus running on the fully merged consortium graph.

```bash
python scripts/measure_lift.py
```

**✅ Check:** It will output a markdown table proving the value of the network, e.g.:

```markdown
# Detection Recall @ 5% FPR

| Detection View | Recall |
|---|---|
| Siloed Average | 37.1% |
| Consortium (Graph Only) | 49.8% |
| Consortium (+ Cypher) | 56.0% |
```
This is the headline result: the consortium delivers a 1.5x improvement in detection recall over a bank acting alone.
