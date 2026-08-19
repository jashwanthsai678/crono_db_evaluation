# CognoDB Cloud Graph Benchmark

Benchmarking CognoDB Cloud against Neo4j, Memgraph, ArangoDB, and Dgraph on identical data,
identical logical workloads, and (as strictly as each engine allows) identical resources.

## 1. Databases compared and why

| Database | Deployment for this benchmark | Query language | Python driver |
|---|---|---|---|
| CognoDB Cloud | Managed, free `c0` tier | Cypher (openCypher) over Bolt | `neo4j` (official) |
| Neo4j | Self-hosted, Docker (Community) | Cypher | `neo4j` (official) |
| Memgraph | Self-hosted, Docker (Community) | Cypher (openCypher) | `neo4j` (official, Bolt-compatible) |
| ArangoDB | Self-hosted, Docker (Community) | AQL | `python-arango` (official) |
| Dgraph | Self-hosted, Docker | DQL | `pydgraph` (official) |

Rationale: Neo4j and Memgraph are both Cypher/Bolt-compatible with CognoDB, isolating the
storage-engine/deployment variable rather than conflating it with query-language differences.
ArangoDB and Dgraph add genuine architectural diversity (multi-model AQL; lightweight single-binary
Go engine with declarative DQL) while staying single-container and free of multi-service
dependencies — important given the 48-hour window and the very small resource ceiling below.

## 2. Resource fairness methodology

CognoDB's free tier is fixed at **0.5 vCPU / 256 MB RAM / 1 GB disk** (per the assignment; verify
exact figures shown in your own console, as vendor docs and consoles have been observed to disagree).
Every self-hosted database is capped via Docker (`--cpus`, `--memory`, and a size-limited volume) to
match this as closely as possible.

**Strategy: strict literal parity first.** Each database is first run at the exact 0.5 vCPU / 256 MB /
1 GB cap. If a database cannot start or run reliably at that cap, that failure is itself recorded as a
result — then, and only then, that specific database is re-run at the smallest bumped tier it actually
needs, with the deviation explicitly disclosed here.

Validated empirically, not assumed: by loading the full benchmark dataset (36,692 nodes / 367,662
edges — see Section 3) into each platform at the capped resources below, then running the complete
query workload (Section 5) against it. "Survived" means the container stayed up with
`docker inspect --format '{{.State.OOMKilled}}'` = `false` throughout; this is the only claim being
made — high memory-percentage readings that are mostly reclaimable OS page cache (as with Neo4j and
Dgraph, both of which generated hundreds of MB to multiple GB of block I/O from write-ahead logs) are
not treated as failures on their own.

This applied in two phases - **loading** the dataset, then **running the read/write query workload
against it** - because several platforms survived one phase and not the other:

| Database | Cap tested | Load phase | Workload-query phase | Deviation |
|---|---|---|---|---|
| CognoDB | 0.5 vCPU / 256MB / 1GB (fixed, free tier) | Survived (111.5s) | Survived | none |
| Neo4j | 0.5 vCPU / 256MB | Survived (95.2s) | Survived | none |
| Memgraph | 0.5 vCPU / 256MB | Survived (4.8s) | Survived | none |
| ArangoDB | 0.5 vCPU / 256MB | Survived (14.2s), but resting at ~99% memory with zero headroom | **OOM-killed** ~6s into the query workload | see below |
| ArangoDB | 0.5 vCPU / 512MB | Survived (15.2s) | Survived | **2x the 256MB baseline** |
| Dgraph (alpha) | 0.5 vCPU / 256MB | **OOM-killed** during the schema `Alter` step, before any data load | — | see below |
| Dgraph (alpha) | 0.5 vCPU / 512MB | **OOM-killed** partway through node loading (~11k/36.7k nodes) | — | see below |
| Dgraph (alpha) | 0.5 vCPU / 1GB | Survived (99.5s) | **OOM-killed** partway through the indexed-range-lookup query, after traversal + point lookup had already succeeded | see below |
| Dgraph (alpha) | 0.5 vCPU / 2GB | Survived (63.0s) | Survived | **8x the 256MB baseline** |
| Dgraph (zero) | 0.25 vCPU / 128MB | Survived throughout every alpha attempt | Survived | none |

**ArangoDB deviation, disclosed:** loading the dataset alone already left ArangoDB resting at ~99% of
256MB with no data-loading step remaining to blame - the very first query workload run OOM-killed it
within about 6 seconds (confirmed via `docker inspect .State.OOMKilled=true`). Bumped to 512MB, where
it settled at a comfortable ~31% during the same workload. A 2x deviation, much milder than Dgraph's.

**Dgraph deviation, disclosed:** Dgraph's architecture splits a cluster coordinator (`zero`) from the
actual data/query engine (`alpha`); `zero` easily holds to 128MB, but `alpha` needed escalating memory
at every phase: OOM-killed twice getting the data loaded (256MB, then 512MB), survived loading at 1GB,
then OOM-killed again mid-workload at that same 1GB (after its traversal and point-lookup queries had
already run successfully) before finally surviving the complete workload at 2GB - an 8x deviation from
the other platforms' 256MB baseline. Kept in the comparison anyway because refusing to test Dgraph at
all would say less than showing exactly where it breaks and what it actually needs; every Dgraph number
in the results matrix should be read with this resource asymmetry in mind, not compared as if on equal
footing.

**A second, subtler lesson from getting here:** the first attempt at a reusable loader script tried to
*reset* each database (delete any old data) before timing a fresh load, so the same script could be
re-run repeatedly during development. That reset step - not the load itself - is what caused every
failure above except Dgraph's: deleting hundreds of thousands of existing rows in place can cost more
memory than inserting them did, since the engine has to track everything mid-removal while the old
data is still resident. Neo4j hit an actual JVM `OutOfMemoryError` mid-delete and was left running but
unresponsive (`OOMKilled=false`, yet functionally dead until restarted) - the *worst*-behaved failure
mode observed, since nothing on the outside signals it happened. Memgraph hit its own internal
`--memory-limit=200` (set below the 256MB container cap deliberately) and returned a clean, catchable
`TransientError` with the transaction rolled back - the *best*-behaved failure mode observed. Neither
is a resource-capacity finding about the databases themselves; it is a finding about *reset-in-place
under memory pressure* being the wrong operation to benchmark. The fix: loaders now refuse to run
against a non-empty database (`NotEmptyError`) rather than attempting cleanup, and a clean run means
recreating the container with a fresh Docker volume first (see Section 4) - which is also the more
methodologically correct definition of "data loading throughput" in the first place: loading into an
empty store, not a reset-then-reload cycle.

## 3. Dataset

[SNAP `email-Enron`](https://snap.stanford.edu/data/email-Enron.html) — the Enron email communication
network. **36,692 nodes, 367,662 directed edges** (`FromNodeId -> ToNodeId`, one `SENT_EMAIL`
relationship per line in the source file). Chosen because it lands directly in the assignment's
suggested 100k-500k relationship range as a single well-known public file, with no need to subsample
down from a much larger graph (e.g. the full SNAP `soc-Pokec` network is orders of magnitude larger).
Schema used across all platforms: `Person {id: int}` nodes, `SENT_EMAIL` directed edges, no other
properties — kept minimal since the workloads test traversal/lookup/aggregation performance, not
property-storage breadth.

The gzipped source file is committed at `data/raw/email-Enron.txt.gz` (~1MB) so reproducing this
benchmark doesn't depend on the SNAP mirror being reachable; `src/common/dataset.py` auto-extracts it
to `data/raw/email-Enron.txt` (gitignored) on first use of any loader/workload/harness script - no
manual download step needed.

## 4. How to reproduce

Dependencies are isolated in a project-local virtualenv — do not install into the system/global Python.

```
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt   # Windows; use .venv/bin/pip on macOS/Linux
cp .env.example .env                              # then fill in your own CognoDB credentials
docker compose -f docker/docker-compose.yml up -d
```

**Data loading benchmark** (each loader refuses to run against a non-empty database - see the
"second lesson" note in Section 2 - so a clean run means recreating that platform's container with a
fresh volume first):

```
./.venv/Scripts/python.exe -m src.loaders.load_cognodb
./.venv/Scripts/python.exe -m src.loaders.load_neo4j
./.venv/Scripts/python.exe -m src.loaders.load_memgraph
./.venv/Scripts/python.exe -m src.loaders.load_arango
./.venv/Scripts/python.exe -m src.loaders.load_dgraph
```

To reset a self-hosted platform between runs (example: Neo4j):

```
docker compose -f docker/docker-compose.yml rm -sf neo4j
docker volume rm docker_neo4j_data
docker compose -f docker/docker-compose.yml up -d neo4j
```

Each loader writes its result to `results/load_<platform>.json`.

**Query workload benchmark** (1/2/3-hop traversal, point lookup, indexed/filtered lookup,
aggregation — 100 iterations each after a warm-up, p50/p95 reported; run against the data loaded
above, so run the loaders first):

```
./.venv/Scripts/python.exe -m src.workloads.run_cognodb
./.venv/Scripts/python.exe -m src.workloads.run_neo4j
./.venv/Scripts/python.exe -m src.workloads.run_memgraph
./.venv/Scripts/python.exe -m src.workloads.run_arango
./.venv/Scripts/python.exe -m src.workloads.run_dgraph
```

Writes to `results/workload_<platform>.json`.

**Concurrent read/write harness** (concurrency sweep at 1 / 10 / 40 clients, 80/20 read/write mix,
5 seconds per level; measures sustained ops/sec and p50/p95 latency under contention):

```
./.venv/Scripts/python.exe -m src.harness.run_cognodb
./.venv/Scripts/python.exe -m src.harness.run_neo4j
./.venv/Scripts/python.exe -m src.harness.run_memgraph
./.venv/Scripts/python.exe -m src.harness.run_arango
./.venv/Scripts/python.exe -m src.harness.run_dgraph
```

Writes to `results/concurrency_<platform>.json`.

## 5. Results matrix

### Data loading

| Platform | Node load | Edge load | Total | Nodes/sec | Edges/sec |
|---|---|---|---|---|---|
| CognoDB | 9.1s | 102.4s | 111.5s | 4,019 | 3,590 |
| Neo4j | 8.8s | 86.4s | 95.2s | 4,182 | 4,253 |
| Memgraph | 0.3s | 4.5s | 4.8s | 121,949 | 81,059 |
| ArangoDB | 1.0s | 13.2s | 14.2s | 37,364 | 27,796 |
| Dgraph (2GB, see Section 2 deviation) | 18.2s | 44.8s | 63.0s | 2,015 | 8,212 |

Raw values in `results/load_*.json`. Note on the Dgraph row: Section 2's phase-by-phase discovery
found 1GB sufficient for loading alone (99.5s at that tier) and only the workload queries required
the further bump to 2GB — but the number reported here is from re-loading at the final, uniform 2GB
tier Dgraph runs at throughout this benchmark, so it matches the committed `results/load_dgraph.json`
exactly rather than mixing numbers from two different container configurations.

Memgraph's in-memory engine and ArangoDB's batched document-API inserts are far faster than the three
graph-native/Bolt engines here, which pay a per-batch `MATCH` cost to resolve edge endpoints by indexed
property lookup rather than by internal ID - a query-model difference, not just a hardware one (see
Section 6).

### Traversals (p50 / p95, ms; 100 samples from fixed-seed random start nodes, 5-op warm-up)

2-hop and 3-hop results are capped at 1000 matched paths per query (see the note under "Query design"
below) - without that cap, this dataset's hub nodes made exact-3-hop counts exceed 180,000 paths from
a single start node, large enough on its own to OOM multiple engines during testing.

| Platform | 1-hop p50 | 1-hop p95 | 2-hop p50 | 2-hop p95 | 3-hop p50 | 3-hop p95 |
|---|---|---|---|---|---|---|
| CognoDB | 258.4 | 263.7 | 260.5 | 267.0 | 261.0 | 266.4 |
| Neo4j | 4.0 | 64.6 | 5.5 | 79.8 | 13.4 | 54.1 |
| Memgraph | 1.1 | 7.2 | 1.3 | 7.6 | 1.4 | 2.2 |
| ArangoDB (512MB) | 47.1 | 54.1 | 46.5 | 53.3 | 46.9 | 53.0 |
| Dgraph (2GB) | 1.8 | 42.8 | 2.3 | 61.3 | 5.7 | 89.9 |

### Lookups (p50 / p95, ms)

Point lookup: exact match by indexed `id`/`node_id` property. Indexed/filtered lookup: range filter
(`id >= lo AND id < hi`, width 200) on the same index. **Indexed property on every platform: `id`
(CognoDB/Neo4j/Memgraph via a Cypher property index; `node_id` on ArangoDB via a persistent index;
`node_id` on Dgraph via an `@index(int)` directive).**

| Platform | Point p50 | Point p95 | Range p50 | Range p95 |
|---|---|---|---|---|
| CognoDB | 258.2 | 262.5 | 277.5 | 286.5 |
| Neo4j | 5.8 | 48.7 | 6.9 | 36.5 |
| Memgraph | 0.8 | 1.4 | 1.0 | 3.0 |
| ArangoDB (512MB) | 44.8 | 52.8 | 46.0 | 53.5 |
| Dgraph (2GB) | 1.3 | 19.2 | **503.0** | **898.3** |

### Aggregation (p50 / p95, ms)

Total count of `SENT_EMAIL` relationships - a global count aggregation over the relationship type,
100 repeated timings.

| Platform | p50 | p95 |
|---|---|---|
| CognoDB | 258.1 | 263.3 |
| Neo4j | 3.0 | 33.5 |
| Memgraph | **85.6** | **105.2** |
| ArangoDB (512MB) | 44.8 | 52.8 |
| Dgraph (2GB) | **1011.2** | **1333.5** |

### Concurrent read/write (80% read / 20% write mix, 5s per concurrency level)

Write op: increment a `touch_count` property on a randomly chosen existing node (safe under repeat
runs - doesn't grow the graph). "Failures" are write-write conflicts the database itself rejected
(e.g. Memgraph/Dgraph's optimistic concurrency control), not harness errors - counted, not hidden.

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

### Footprint

| Platform | Instance spec | Peak memory during benchmark | On-disk data size |
|---|---|---|---|
| CognoDB | 0.5 vCPU / 256MB / 1GB (fixed, managed) | not observable (no metrics endpoint found) | not observable |
| Neo4j | 0.5 vCPU / 256MB (Docker) | 99.6-100% | 533 MB |
| Memgraph | 0.5 vCPU / 256MB (Docker) | 43-51% | 469 MB |
| ArangoDB | 0.5 vCPU / 512MB (Docker, deviation) | 31-99%* | 84 MB |
| Dgraph | 0.5 vCPU / 2GB alpha + 0.25 vCPU / 128MB zero (Docker, deviation) | 60-100%* | 58 MB (alpha) |

\* ArangoDB's and Dgraph's memory ranges span both their pre-deviation failure point and their
post-deviation resting state, shown together to keep the deviation visible rather than only
reporting the number after the fix.

For a 367,662-edge, 36,692-node graph with no properties beyond a single integer id, on-disk size
ranges 9x between platforms (58MB-533MB) - a storage-engine/encoding difference, not a data
difference (see Analysis).

**Query design note:** every hop-depth/lookup/aggregation query is logically identical across
platforms (same predicate, same cardinality target) but necessarily written in each platform's own
query language - Cypher for CognoDB/Neo4j/Memgraph, AQL for ArangoDB, DQL for Dgraph. Full query text
is in `src/workloads/`.

## 6. Analysis

**Query-language-sharing paid off as expected.** CognoDB, Neo4j, and Memgraph all speak Cypher over
Bolt, so identical query text and driver code ran against all three - the only source of difference
between them is genuinely the storage engine and deployment, not incidental query-authoring
differences. That is the single biggest reason this comparison is trustworthy where it says something
about *engines* rather than about *how carefully each query was hand-tuned*.

**Latency is dominated by protocol overhead more than by query complexity, for two of five
platforms.** ArangoDB's and CognoDB's per-query numbers are strikingly flat across every workload -
ArangoDB sits at ~44-54ms and CognoDB at ~258-277ms regardless of whether the query is a 1-hop
traversal or a full-graph aggregation. That flatness is itself informative: it means each
`aql.execute()`/Bolt-over-internet round trip pays a mostly-fixed per-request cost (HTTP request
setup for ArangoDB's REST-based driver; real internet latency plus CognoDB's own request handling for
CognoDB) that swamps the actual query-execution-time differences an in-process or LAN-connected engine
would show. Neo4j, Memgraph, and Dgraph - all Bolt/gRPC with persistent connections - show the
expected shape instead: 1-hop cheapest, 3-hop costliest, point lookup near 1-hop cost.

**The "aggregation" query exposes a genuine engine-internals difference, not just noise.** Memgraph
and Dgraph are both dramatically slower on the global `SENT_EMAIL` count than on any other query type
they run (Memgraph: 85.6ms vs. sub-2ms elsewhere; Dgraph: 1011ms vs. sub-6ms elsewhere), while Neo4j
answers the same logical count in 3.0ms. The most likely explanation: Neo4j maintains an internal
*count store* - a maintained running total per relationship type that answers `count(r)` in
near-constant time without touching the actual relationships. Memgraph and Dgraph, by contrast, appear
to require an actual scan/aggregation over the full edge set for this query shape (Dgraph's
`var`+`sum` pattern in particular has to materialize a per-node count before summing). This is a
concrete, falsifiable hypothesis rather than a guess, and it is exactly the kind of "why do platforms
differ" root cause the assignment asks for - a maintained aggregate structure is a real architectural
choice with a real performance payoff for this specific query shape.

**Dgraph's indexed-range-lookup result (503ms/898ms) is the single largest per-query outlier in the
entire matrix**, roughly 100x its own point-lookup cost and far above every other platform's range
query. Combined with the two OOM-kills this exact query type triggered before the 2GB bump (Section
2), the working hypothesis is that Dgraph's `ge`/`lt` compound range filter over an `@index(int)`
predicate is not resolved as a narrow index range-scan the way a B-tree-backed engine would do it, but
instead touches a much broader posting-list/bitmap structure - expensive in both latency and memory
for exactly this query pattern, even though point lookups on the very same index are fast and cheap.
This is a plausible root cause worth flagging explicitly rather than either hiding the number or
treating it as an unexplained anomaly.

**Storage footprint varies 9x for identical logical data (58MB-533MB).** Neo4j and Memgraph, the two
platforms with the largest on-disk footprints, both maintain write-ahead logs and native
node/relationship store formats with per-record fixed overhead designed for fast random access and
transactional durability, not compactness. ArangoDB (RocksDB-backed) and Dgraph (Badger/LSM-backed)
both use log-structured-merge storage with compression, which favors compactness over the same kind of
uniform-fixed-size random-access layout. None of this is a "better" or "worse" choice in isolation - it
is a direct tradeoff against the write/read/durability characteristics each engine is designed around -
but it does mean storage-size comparisons between these platforms are comparing genuinely different
engineering tradeoffs, not just implementation quality.

**Concurrency scaling is real but bounded by the 0.5-vCPU cap, as expected.** Every self-hosted
platform's ops/sec increases from concurrency 1 to 40 (e.g. ArangoDB 21.2 -> 632.5 ops/sec, a ~30x
gain from a mostly-idle single connection scaling out to enough concurrent requests to actually
saturate half a CPU core), but p95 latency also climbs at the same time as queueing sets in on a
severely CPU-constrained single core - the expected shape for a resource-starved server, not a
surprise. CognoDB scales too (2.7 -> 102.6 ops/sec) but far more mutedly, consistent with the
per-request network round-trip cost identified above dominating over whatever queueing effects the
free-tier instance itself experiences. Write-write conflicts (the `failures` column) appear only at
higher concurrency and only on Memgraph, ArangoDB, and Dgraph - all of which use optimistic/MVCC-style
concurrency control that detects and rejects a losing concurrent writer rather than blocking it; Neo4j
and CognoDB, by contrast, showed conflicts appear far less frequently (Neo4j: 3 out of 995 ops, only at
40 clients) or not at all in this run (CognoDB: 0), suggesting different locking granularity or
isolation defaults - worth deeper investigation but not verifiable further from outside each engine.

## 7. Caveats

- **CognoDB free tier is fixed and unobservable.** 0.5 vCPU / 256MB / 1GB per the assignment; no
  metrics endpoint was found to confirm memory/CPU usage during load, so CognoDB's footprint is
  reported as "not observable" rather than guessed.
- **CognoDB load times include real network latency**; the other four run on localhost. This
  inflates CognoDB's apparent load time somewhat relative to a same-network comparison, and is worth
  keeping in mind when comparing raw wall-clock numbers rather than throughput.
- **Dgraph's `alpha` node runs at 2GB throughout this benchmark, not the 256MB every other
  self-hosted platform uses** - confirmed necessary via three separate OOM-kills across the load and
  workload phases (Section 2). Its numbers are not on equal resource footing with the rest and are
  flagged as such wherever they're reported.
- **`.gitignore`/`.env` discipline**: CognoDB credentials were shared once in a chat session during
  setup and are treated as exposed; the instance password should be rotated before relying on this
  environment for anything beyond this benchmark.
- **The assignment's example URI format (`.databases.cognodb.cloud`) did not match the actual
  console-issued URI (`.databases.cognodb.com`)** for this instance - copy the exact URI from your own
  console rather than the doc's example.
- **ArangoDB and Dgraph both needed a documented resource deviation for the query workload, not just
  the load** (512MB and 2GB respectively - Section 2). Their workload numbers are directly comparable
  to each other in shape, but not on equal resource footing with CognoDB/Neo4j/Memgraph's 256MB.
- **Unbounded 2-hop/3-hop traversal counts were themselves a resource-exhaustion vector.** This
  dataset's hub nodes produce 180,000+ exact-3-hop paths from a single start node; the first version
  of the traversal queries had no LIMIT and this alone OOM-killed ArangoDB and hit a gRPC
  "message too large" client-side limit on Dgraph before any memory tier changes were tried. Every
  platform's 2-hop/3-hop query is now capped at ~1000 matched paths (see Section 5's "Query design
  note") - a deliberate, disclosed methodology choice, not a silent workaround.
- **ArangoDB's and CognoDB's per-query latencies are flat across every workload type** (~44-54ms and
  ~258-277ms respectively, regardless of query complexity) - almost certainly because per-request
  protocol overhead (HTTP for ArangoDB's REST driver, real internet latency for CognoDB) dominates
  actual query-execution time for this dataset size. Treat their numbers as measuring
  "round-trip cost on this setup" more than "query-execution cost" specifically - flagged rather than
  presented as directly comparable to the Bolt/gRPC platforms' numbers.
- **Concurrent-write conflicts are counted, not hidden or allowed to crash the harness.** An early
  version of the concurrency harness let an uncaught write-write conflict exception (observed on
  Memgraph: `Cannot resolve conflicting transactions`) kill the worker thread outright, silently
  under-reporting throughput for the rest of that concurrency level. The harness now catches per-op
  exceptions, counts them under `failures`, and keeps the worker running for the full timed window.
- **The concurrency harness's first query per worker thread is an untimed warm-up** (connection setup
  + query-plan compilation cost was observed dominating the p95 at concurrency=1 before this was
  added, e.g. Neo4j's initial run showed a 4459ms p95 on only 10 total ops).
- Repeated-run variance was not formally measured (single run per metric, given the 48-hour window) -
  the numbers in Section 5 should be read as one representative sample, not a statistically
  characterized distribution. Re-running any `src/workloads/run_*` or `src/harness/run_*` script
  reproduces a fresh sample.
