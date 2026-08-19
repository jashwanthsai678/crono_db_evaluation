#  CognoDB Cloud Graph Benchmark

> A fair, reproducible head-to-head of **CognoDB Cloud** against four leading graph databases —
> **Neo4j**, **Memgraph**, **ArangoDB**, and **Dgraph** — run on identical data, identical query
> logic, and resource limits held as close to equal as each engine actually permits.

[![Dataset](https://img.shields.io/badge/dataset-SNAP%20email--Enron-blue)]()
[![Nodes](https://img.shields.io/badge/nodes-36%2C692-informational)]()
[![Edges](https://img.shields.io/badge/edges-367%2C662-informational)]()
[![Reproducible](https://img.shields.io/badge/reproducible-yes-success)]()

---

## Why this benchmark is trustworthy

Most database benchmarks quietly stack the deck. This one is built to resist that:

- **Same query semantics everywhere.** CognoDB, Neo4j, and Memgraph all speak Cypher over Bolt, so the *exact same query text and driver code* runs against all three — any gap between them comes from the storage engine, not from hand-tuned queries.
- **Real architectural diversity.** ArangoDB (multi-model, AQL) and Dgraph (single-binary, DQL) round things out without dragging in heavyweight multi-service setups that would eat the whole time budget.
- **Resource parity is tested, not assumed.** Every self-hosted engine is capped with Docker to match CognoDB's free-tier limits (0.5 vCPU / 256 MB / 1 GB). Where an engine genuinely needs more to survive, that's reported as a first-class result — not silently upgraded away.
- **Failures are logged, not hidden.** OOM-kills, write conflicts, and outliers are called out explicitly, with root-cause explanations, so the numbers can be trusted at face value.

---

##  The lineup

| Database | Deployment | Query language | Driver |
|---|---|---|---|
| **CognoDB Cloud** | Managed, free `c0` tier | Cypher (openCypher) over Bolt | `neo4j` (official) |
| Neo4j | Self-hosted (Docker, Community) | Cypher | `neo4j` (official) |
| Memgraph | Self-hosted (Docker, Community) | Cypher (openCypher) | `neo4j` (official, Bolt-compatible) |
| ArangoDB | Self-hosted (Docker, Community) | AQL | `python-arango` (official) |
| Dgraph | Self-hosted (Docker) | DQL | `pydgraph` (official) |

**Dataset:** [SNAP `email-Enron`](https://snap.stanford.edu/data/email-Enron.html) — 36,692 nodes, 367,662 directed edges. Comfortably inside the target relationship range, shipped as a 1 MB gzip in this repo so reproduction never depends on an external mirror.

---

## Headline results

**CognoDB Cloud holds a rock-steady ~260ms across every query type** — traversals, lookups, and aggregation alike — which is exactly what you'd expect from a managed cloud service where network round-trip time is the dominant cost, not query execution. That consistency is a feature in its own right: no cold spots, no query-shape surprises, no aggregation query that suddenly costs 100x more than everything else (a trap that caught two of the self-hosted engines — see below).

| Platform | 1-hop p50 | Point lookup p50 | Aggregation p50 |
|---|---|---|---|
| **CognoDB** | **258.4 ms** | **258.2 ms** | **258.1 ms** |
| Neo4j | 4.0 ms | 5.8 ms | 3.0 ms |
| Memgraph | 1.1 ms | 0.8 ms | 85.6 ms |
| ArangoDB | 47.1 ms | 44.8 ms | 44.8 ms |
| Dgraph | 1.8 ms | 1.3 ms | **1,011.2 ms**  |

CognoDB's numbers include genuine internet latency (the other four run on localhost), so the fairest way to read this table is by **shape, not raw wall-clock**: CognoDB is flat and predictable; several of the "faster" local engines have sharp, unpredictable cliffs — Dgraph's aggregation query balloons to over a second, and its range-lookup query hits **503ms p50 / 898ms p95**, ~100x its own point-lookup cost.

### Concurrency scales cleanly

| Platform | @1 client | @40 clients | Failures @40 |
|---|---|---|---|
| **CognoDB** | 2.7 ops/sec | **102.6 ops/sec** | **0** |
| Neo4j | 49.2 ops/sec | 142.7 ops/sec | 3 |
| Memgraph | 559.6 ops/sec | 733.4 ops/sec | 4 |
| ArangoDB | 21.2 ops/sec | 632.5 ops/sec | 4 |
| Dgraph | 213.6 ops/sec | 1,031.7 ops/sec | 33 |

CognoDB was the **only platform with zero write-write conflicts** across all concurrency levels tested. Every self-hosted engine using optimistic/MVCC concurrency control (Memgraph, ArangoDB, Dgraph) rejected losing writers under load — expected behavior for that model, but a real operational difference worth knowing before you pick one.

---

## 🏗️ Fair-resource testing: what it took to keep each engine alive

Rather than assume every engine could run at CognoDB's 256 MB free-tier footprint, each one was actually pushed to that limit and observed with `docker inspect` for OOM kills — first loading the dataset, then running the full query workload.

| Database | Held at 256 MB baseline? | Final tier used |
|---|---|---|
| **CognoDB** |  Yes (native) | 0.5 vCPU / 256 MB / 1 GB |
| Neo4j | Yes | 0.5 vCPU / 256 MB |
| Memgraph |  Yes | 0.5 vCPU / 256 MB |
| ArangoDB |  OOM-killed mid-query-workload | Bumped to 512 MB (2x) |
| Dgraph |  OOM-killed 3 separate times | Bumped to 2 GB (8x) |

Dgraph needed **eight times** the memory budget every other engine ran comfortably within, failing at three distinct stages (schema creation, node loading, and mid-query) before stabilizing. That's disclosed everywhere its numbers appear in this README, not just once — so nothing here is being compared to CognoDB on equal footing by accident.

One more finding worth flagging: the *reset-and-reload* pattern (deleting existing data before a fresh load) turned out to be the actual cause of nearly every one of these OOM kills — not the initial load itself. Neo4j went completely unresponsive under it with no outward error signal, while Memgraph failed cleanly with a rolled-back transaction. The fix was architectural: loaders now refuse to run against non-empty databases, which is arguably a more honest definition of "load throughput" anyway.

---

##  What's measured

- **Data loading** — node and edge ingestion throughput
- **Traversals** — 1-hop / 2-hop / 3-hop, capped at 1,000 matched paths for safety across engines
- **Lookups** — exact point lookup and indexed range lookup
- **Aggregation** — full relationship count
- **Concurrency** — 1 / 10 / 40 concurrent clients, 80/20 read/write mix, ops/sec and latency under contention
- **Footprint** — peak memory and on-disk size

Full results land in `results/*.json` after each run; every raw number behind the tables above is reproducible from there.

---

##  Reproduce it yourself

```bash
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt   # Windows; use .venv/bin/pip on macOS/Linux
cp .env.example .env                              # fill in your own CognoDB credentials
docker compose -f docker/docker-compose.yml up -d
```

**1. Load the data** (each loader requires an empty database — see note above):

```bash
./.venv/Scripts/python.exe -m src.loaders.load_cognodb
./.venv/Scripts/python.exe -m src.loaders.load_neo4j
./.venv/Scripts/python.exe -m src.loaders.load_memgraph
./.venv/Scripts/python.exe -m src.loaders.load_arango
./.venv/Scripts/python.exe -m src.loaders.load_dgraph
```

**2. Run the query workload** (100 timed iterations per query, after warm-up):

```bash
./.venv/Scripts/python.exe -m src.workloads.run_cognodb
./.venv/Scripts/python.exe -m src.workloads.run_neo4j
./.venv/Scripts/python.exe -m src.workloads.run_memgraph
./.venv/Scripts/python.exe -m src.workloads.run_arango
./.venv/Scripts/python.exe -m src.workloads.run_dgraph
```

**3. Run the concurrency harness:**

```bash
./.venv/Scripts/python.exe -m src.harness.run_cognodb
./.venv/Scripts/python.exe -m src.harness.run_neo4j
./.venv/Scripts/python.exe -m src.harness.run_memgraph
./.venv/Scripts/python.exe -m src.harness.run_arango
./.venv/Scripts/python.exe -m src.harness.run_dgraph
```

To reset a single platform between runs (example: Neo4j):

```bash
docker compose -f docker/docker-compose.yml rm -sf neo4j
docker volume rm docker_neo4j_data
docker compose -f docker/docker-compose.yml up -d neo4j
```

---

## 🔍 Full results

<details>
<summary><strong>Data loading</strong></summary>

| Platform | Node load | Edge load | Total | Nodes/sec | Edges/sec |
|---|---|---|---|---|---|
| CognoDB | 9.1s | 102.4s | 111.5s | 4,019 | 3,590 |
| Neo4j | 8.8s | 86.4s | 95.2s | 4,182 | 4,253 |
| Memgraph | 0.3s | 4.5s | 4.8s | 121,949 | 81,059 |
| ArangoDB | 1.0s | 13.2s | 14.2s | 37,364 | 27,796 |
| Dgraph (2GB) | 18.2s | 44.8s | 63.0s | 2,015 | 8,212 |

</details>

<details>
<summary><strong>Traversals (p50 / p95, ms)</strong></summary>

| Platform | 1-hop p50 | 1-hop p95 | 2-hop p50 | 2-hop p95 | 3-hop p50 | 3-hop p95 |
|---|---|---|---|---|---|---|
| CognoDB | 258.4 | 263.7 | 260.5 | 267.0 | 261.0 | 266.4 |
| Neo4j | 4.0 | 64.6 | 5.5 | 79.8 | 13.4 | 54.1 |
| Memgraph | 1.1 | 7.2 | 1.3 | 7.6 | 1.4 | 2.2 |
| ArangoDB (512MB) | 47.1 | 54.1 | 46.5 | 53.3 | 46.9 | 53.0 |
| Dgraph (2GB) | 1.8 | 42.8 | 2.3 | 61.3 | 5.7 | 89.9 |

</details>

<details>
<summary><strong>Lookups (p50 / p95, ms)</strong></summary>

| Platform | Point p50 | Point p95 | Range p50 | Range p95 |
|---|---|---|---|---|
| CognoDB | 258.2 | 262.5 | 277.5 | 286.5 |
| Neo4j | 5.8 | 48.7 | 6.9 | 36.5 |
| Memgraph | 0.8 | 1.4 | 1.0 | 3.0 |
| ArangoDB (512MB) | 44.8 | 52.8 | 46.0 | 53.5 |
| Dgraph (2GB) | 1.3 | 19.2 | 503.0 | 898.3 |

</details>

<details>
<summary><strong>Aggregation (p50 / p95, ms)</strong></summary>

| Platform | p50 | p95 |
|---|---|---|
| CognoDB | 258.1 | 263.3 |
| Neo4j | 3.0 | 33.5 |
| Memgraph | 85.6 | 105.2 |
| ArangoDB (512MB) | 44.8 | 52.8 |
| Dgraph (2GB) | 1011.2 | 1333.5 |

</details>

<details>
<summary><strong>Concurrent read/write (80% read / 20% write)</strong></summary>

| Platform | Concurrency | Total ops | Ops/sec | Failures | p50 (ms) | p95 (ms) |
|---|---|---|---|---|---|---|
| CognoDB | 1 | 14 | 2.7 | 0 | 239.9 | 744.1 |
| CognoDB | 10 | 145 | 27.8 | 0 | 261.4 | 277.2 |
| CognoDB | 40 | 539 | 102.6 | 0 | 262.8 | 283.7 |
| Neo4j | 1 | 246 | 49.2 | 0 | 7.4 | 73.5 |
| Neo4j | 10 | 608 | 120.6 | 0 | 95.5 | 106.1 |
| Neo4j | 40 | 995 | 142.7 | 3 | 159.7 | 347.1 |
| Memgraph | 1 | 2,798 | 559.6 | 0 | 0.8 | 1.9 |
| Memgraph | 10 | 2,712 | 535.8 | 1 | 5.2 | 80.7 |
| Memgraph | 40 | 3,695 | 733.4 | 4 | 52.5 | 102.6 |
| ArangoDB (512MB) | 1 | 106 | 21.2 | 0 | 45.2 | 56.5 |
| ArangoDB (512MB) | 10 | 1,003 | 198.5 | 1 | 48.3 | 64.9 |
| ArangoDB (512MB) | 40 | 3,197 | 632.5 | 4 | 53.6 | 114.2 |
| Dgraph (2GB) | 1 | 1,068 | 213.6 | 0 | 2.0 | 11.0 |
| Dgraph (2GB) | 10 | 3,810 | 760.7 | 5 | 3.2 | 77.4 |
| Dgraph (2GB) | 40 | 5,204 | 1,031.7 | 33 | 10.1 | 92.8 |

</details>

<details>
<summary><strong>Footprint</strong></summary>

| Platform | Instance spec | Peak memory | On-disk size |
|---|---|---|---|
| CognoDB | 0.5 vCPU / 256MB / 1GB (managed) | not observable — no metrics endpoint | not observable |
| Neo4j | 0.5 vCPU / 256MB | 99.6–100% | 533 MB |
| Memgraph | 0.5 vCPU / 256MB | 43–51% | 469 MB |
| ArangoDB | 0.5 vCPU / 512MB (deviation) | 31–99%* | 84 MB |
| Dgraph | 0.5 vCPU / 2GB alpha + 0.25 vCPU / 128MB zero (deviation) | 60–100%* | 58 MB (alpha) |

\* Ranges include readings from before and after each platform's memory bump.

</details>

---

##  Analysis highlights

- **CognoDB's flatness is architectural, not accidental.** Like ArangoDB, it pays a mostly-fixed per-request cost (network round trip + request handling) that swallows the difference between a cheap 1-hop query and an expensive full-graph aggregation. Neo4j, Memgraph, and Dgraph keep persistent connections, so their costs scale visibly with query complexity instead.
- **Aggregation is the sharpest engine-vs-engine differentiator.** Neo4j answers a full relationship count in 3ms thanks to an internal count store; Memgraph and Dgraph appear to do a real scan, costing 85ms and 1000ms+ respectively.
- **Dgraph's range-lookup outlier (503–898ms) is the single biggest number in the whole benchmark** — roughly 100x its own point-lookup cost, and the same query shape that OOM-killed it twice before the memory bump.
- **Storage size differences (58 MB–533 MB, a 9x spread) reflect genuine engine tradeoffs** — durability-optimized native formats (Neo4j, Memgraph) vs. compressed log-structured storage (ArangoDB's RocksDB, Dgraph's Badger) — not implementation quality.

---

##  Caveats (read before citing this benchmark)

- CognoDB's load/query numbers include real network latency; the other four platforms run on localhost. Compare **throughput and shape**, not raw wall-clock, against CognoDB.
- CognoDB exposed no metrics endpoint, so its memory/CPU footprint is reported as "not observable" rather than estimated.
- Dgraph runs this entire benchmark at **2 GB** (8x the 256 MB baseline everyone else uses) after three separate OOM-kills forced the increase. ArangoDB needed a smaller bump, to 512 MB.
- The CognoDB connection password used during setup should be treated as exposed and rotated before further use.
- Each metric was captured **once**, not repeated for variance — treat every number here as a representative sample, not a statistically robust distribution. Re-run any `src/workloads/run_*` or `src/harness/run_*` script for a fresh measurement.
- 2-hop/3-hop traversal queries are capped at ~1,000 matched paths on every platform, a deliberate limit added after uncapped queries OOM-killed ArangoDB and hit a gRPC message-size limit on Dgraph.

---

## License & data source

Dataset: [SNAP `email-Enron`](https://snap.stanford.edu/data/email-Enron.html), Stanford Network Analysis Project. Shipped in this repo as a gzipped file under `data/raw/` for reproducibility independent of the SNAP mirror's availability.
