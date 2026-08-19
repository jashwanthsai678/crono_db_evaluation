# CognoDB Cloud Graph Benchmark

This benchmarks CognoDB Cloud against four other graph databases — Neo4j, Memgraph, ArangoDB, and
Dgraph — on the same dataset, the same queries, and resource limits kept as close to equal as each
engine actually allows.

## 1. Databases compared, and why these four

| Database | Deployment for this benchmark | Query language | Python driver |
|---|---|---|---|
| CognoDB Cloud | Managed, free `c0` tier | Cypher (openCypher) over Bolt | `neo4j` (official) |
| Neo4j | Self-hosted, Docker (Community) | Cypher | `neo4j` (official) |
| Memgraph | Self-hosted, Docker (Community) | Cypher (openCypher) | `neo4j` (official, Bolt-compatible) |
| ArangoDB | Self-hosted, Docker (Community) | AQL | `python-arango` (official) |
| Dgraph | Self-hosted, Docker | DQL | `pydgraph` (official) |

CognoDB speaks Cypher over Bolt, and so do Neo4j and Memgraph — that's not a coincidence in how I
picked them. Using the same query language and the same driver against three of the five platforms
means the only thing actually changing between them is the storage engine and how it's deployed, not
how carefully I hand-tuned each query. ArangoDB and Dgraph then bring in real architectural variety —
a multi-model document/graph store with its own query language, and a lightweight single-binary
engine with a declarative query language — without dragging in a multi-service setup (Cassandra +
Elasticsearch for JanusGraph, for instance) that would have eaten most of the time budget just getting
it running.

## 2. Resource fairness

CognoDB's free tier is fixed at **0.5 vCPU / 256 MB RAM / 1 GB disk** (per the assignment — check your
own console for the exact numbers, since the vendor's docs and console have been seen to disagree on
this). Every self-hosted database is capped through Docker (`--cpus`, `--memory`) to match that as
closely as possible.

The approach: try strict parity first. Run every database at the literal 0.5 vCPU / 256 MB cap. If one
can't stay up at that cap, that failure is a result in its own right — and only then does it get
re-run at the smallest tier that actually keeps it alive, with the change written down here rather
than quietly upgraded away.

I didn't just assume this would work — I tested it, twice: once by loading the full dataset (36,692
nodes / 367,662 edges — Section 3) into each platform at the capped resources, and again by running
the whole query workload against the loaded data. "Survived" here means `docker inspect` reports
`OOMKilled: false` the whole time. That's a deliberately narrow claim. A couple of these databases
(Neo4j, Dgraph) show memory sitting near 100% for long stretches, but most of that turned out to be
ordinary, reclaimable OS page cache built up from write-ahead log I/O, not real memory pressure — so a
scary-looking percentage on its own isn't treated as a failure.

Two platforms needed more than the baseline, and it showed up at different points for each:

| Database | Cap tested | Load phase | Query-workload phase | Deviation |
|---|---|---|---|---|
| CognoDB | 0.5 vCPU / 256MB / 1GB (fixed, free tier) | Survived (111.5s) | Survived | none |
| Neo4j | 0.5 vCPU / 256MB | Survived (95.2s) | Survived | none |
| Memgraph | 0.5 vCPU / 256MB | Survived (4.8s) | Survived | none |
| ArangoDB | 0.5 vCPU / 256MB | Survived (14.2s), but sitting at ~99% memory with no headroom left | OOM-killed ~6s into the query workload | see below |
| ArangoDB | 0.5 vCPU / 512MB | Survived (15.2s) | Survived | 2x the 256MB baseline |
| Dgraph (alpha) | 0.5 vCPU / 256MB | OOM-killed during the schema `Alter` step, before any data went in | — | see below |
| Dgraph (alpha) | 0.5 vCPU / 512MB | OOM-killed partway through node loading (~11k of 36.7k nodes) | — | see below |
| Dgraph (alpha) | 0.5 vCPU / 1GB | Survived (99.5s) | OOM-killed partway through the indexed range-lookup query, after traversal and point lookup had already worked | see below |
| Dgraph (alpha) | 0.5 vCPU / 2GB | Survived (63.0s) | Survived | 8x the 256MB baseline |
| Dgraph (zero) | 0.25 vCPU / 128MB | Fine every time, all four alpha attempts | Fine | none |

**On ArangoDB:** just loading the dataset left it resting at close to 99% of the 256MB cap with
nothing left in reserve. The first time I actually ran a query workload against it, it got OOM-killed
about six seconds in (`docker inspect` confirmed `OOMKilled: true`). Bumping it to 512MB fixed this —
it settled at a comfortable ~31% for the same workload. A 2x bump, and a fairly mild one compared to
Dgraph's.

**On Dgraph:** its architecture splits a cluster coordinator (`zero`) from the actual data/query
engine (`alpha`). `zero` never had any trouble staying under 128MB. `alpha` is a different story — it
got OOM-killed applying its own schema at 256MB, OOM-killed again partway through loading at 512MB,
finally loaded fine at 1GB, and then got OOM-killed again *mid-workload* at that same 1GB (after its
traversal and point-lookup queries had already run without issue). It only became fully stable at 2GB
— eight times the 256MB everyone else runs at. I kept it in the comparison anyway, because leaving
Dgraph out entirely would tell you less than showing exactly where it falls over and how much room it
actually needs. Just don't read its numbers as apples-to-apples with the others on hardware — they
aren't.

**One more thing worth writing down, because it wasn't obvious going in:** the first version of the
data loader tried to reset each database — delete whatever old data was there — before timing a fresh
load, so the same script could be re-run during development without manual cleanup. That reset step,
not the load itself, is what caused nearly every failure above except Dgraph's. Deleting hundreds of
thousands of existing rows in place can cost *more* memory than inserting them did in the first place,
because the engine has to keep track of everything mid-removal while the old data is still sitting in
memory. Neo4j hit a real JVM `OutOfMemoryError` in the middle of one of these deletes and was left
running but completely unresponsive — Docker still reported the container as up, but nothing was
happening inside it. That's arguably the worst way for something to fail, since there's no outward
signal that anything's wrong. Memgraph, on the other hand, hit its own internal `--memory-limit=200`
(set below the container's 256MB cap on purpose) and just returned a clean error with the transaction
rolled back — the database itself stayed completely healthy afterward. Neither of these says anything
about how much data either engine can hold; it's really a lesson about resetting in place under memory
pressure being the wrong thing to do at all. The fix was to stop trying: loaders now simply refuse to
run against a database that already has data in it, and a clean run means recreating the container
with a fresh volume first (Section 4). Which, honestly, is also just a more honest definition of "load
throughput" to begin with — loading into something empty, not resetting and reloading in one script.

## 3. Dataset

[SNAP `email-Enron`](https://snap.stanford.edu/data/email-Enron.html) — the Enron email network.
**36,692 nodes, 367,662 directed edges** (`FromNodeId -> ToNodeId`, one `SENT_EMAIL` relationship per
line). I picked it because it sits comfortably inside the assignment's suggested 100k–500k
relationship range as one plain public file, without having to cut down a much bigger graph first (the
full SNAP `soc-Pokec` network, for comparison, is orders of magnitude larger). The schema is the same
everywhere: `Person {id: int}` nodes and `SENT_EMAIL` directed edges, nothing else — the workloads are
about traversal, lookup, and aggregation performance, not how well each engine stores extra properties.

The gzipped file is committed at `data/raw/email-Enron.txt.gz` (about 1MB), so reproducing this
doesn't depend on the SNAP mirror being up. `src/common/dataset.py` unpacks it to
`data/raw/email-Enron.txt` automatically the first time any loader, workload, or harness script runs —
nothing to download by hand.

## 4. How to reproduce

Dependencies live in a project-local virtualenv — don't install them into your system Python.

```
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt   # Windows; use .venv/bin/pip on macOS/Linux
cp .env.example .env                              # then fill in your own CognoDB credentials
docker compose -f docker/docker-compose.yml up -d
```

**Data loading.** Each loader refuses to run against a database that isn't empty (see the note in
Section 2), so a clean run means recreating that platform's container with a fresh volume first:

```
./.venv/Scripts/python.exe -m src.loaders.load_cognodb
./.venv/Scripts/python.exe -m src.loaders.load_neo4j
./.venv/Scripts/python.exe -m src.loaders.load_memgraph
./.venv/Scripts/python.exe -m src.loaders.load_arango
./.venv/Scripts/python.exe -m src.loaders.load_dgraph
```

To reset one platform between runs, for example Neo4j:

```
docker compose -f docker/docker-compose.yml rm -sf neo4j
docker volume rm docker_neo4j_data
docker compose -f docker/docker-compose.yml up -d neo4j
```

Each loader writes to `results/load_<platform>.json`.

**Query workload** — 1/2/3-hop traversal, point lookup, indexed/filtered lookup, aggregation. 100
timed iterations each after a short warm-up, p50/p95 reported. Run against data that's already
loaded, so do the loaders first:

```
./.venv/Scripts/python.exe -m src.workloads.run_cognodb
./.venv/Scripts/python.exe -m src.workloads.run_neo4j
./.venv/Scripts/python.exe -m src.workloads.run_memgraph
./.venv/Scripts/python.exe -m src.workloads.run_arango
./.venv/Scripts/python.exe -m src.workloads.run_dgraph
```

Writes to `results/workload_<platform>.json`.

**Concurrent read/write harness** — 1 / 10 / 40 concurrent clients, 80/20 read/write mix, 5 seconds
per concurrency level, sustained ops/sec and p50/p95 latency under contention:

```
./.venv/Scripts/python.exe -m src.harness.run_cognodb
./.venv/Scripts/python.exe -m src.harness.run_neo4j
./.venv/Scripts/python.exe -m src.harness.run_memgraph
./.venv/Scripts/python.exe -m src.harness.run_arango
./.venv/Scripts/python.exe -m src.harness.run_dgraph
```

Writes to `results/concurrency_<platform>.json`.

## 5. Results

### Data loading

| Platform | Node load | Edge load | Total | Nodes/sec | Edges/sec |
|---|---|---|---|---|---|
| CognoDB | 9.1s | 102.4s | 111.5s | 4,019 | 3,590 |
| Neo4j | 8.8s | 86.4s | 95.2s | 4,182 | 4,253 |
| Memgraph | 0.3s | 4.5s | 4.8s | 121,949 | 81,059 |
| ArangoDB | 1.0s | 13.2s | 14.2s | 37,364 | 27,796 |
| Dgraph (2GB — see Section 2) | 18.2s | 44.8s | 63.0s | 2,015 | 8,212 |

Raw numbers are in `results/load_*.json`. One note on the Dgraph row: Section 2 found that 1GB was
actually enough to load the data (99.5s at that tier) and it was only the query workload that forced
the jump to 2GB. But the number above comes from re-loading at the final 2GB tier Dgraph runs at for
the rest of this benchmark, so it matches what's actually sitting in `results/load_dgraph.json` rather
than mixing numbers from two different container setups.

Memgraph's in-memory engine and ArangoDB's batched document inserts are both a lot faster here than
the three Bolt-based engines, which pay a `MATCH` cost per batch to resolve edge endpoints by an
indexed property lookup instead of an internal ID. That's a difference in how the query is shaped,
not just raw hardware (more in Section 6).

### Traversals (p50 / p95, ms — 100 samples, fixed-seed random start nodes, 5-query warm-up)

2-hop and 3-hop queries are capped at 1000 matched paths each (see the query-design note below this
table). Without that cap, this dataset's more connected nodes push the exact 3-hop count past 180,000
paths from a single starting node — big enough on its own to OOM more than one of these engines during
testing.

| Platform | 1-hop p50 | 1-hop p95 | 2-hop p50 | 2-hop p95 | 3-hop p50 | 3-hop p95 |
|---|---|---|---|---|---|---|
| CognoDB | 258.4 | 263.7 | 260.5 | 267.0 | 261.0 | 266.4 |
| Neo4j | 4.0 | 64.6 | 5.5 | 79.8 | 13.4 | 54.1 |
| Memgraph | 1.1 | 7.2 | 1.3 | 7.6 | 1.4 | 2.2 |
| ArangoDB (512MB) | 47.1 | 54.1 | 46.5 | 53.3 | 46.9 | 53.0 |
| Dgraph (2GB) | 1.8 | 42.8 | 2.3 | 61.3 | 5.7 | 89.9 |

### Lookups (p50 / p95, ms)

Point lookup is an exact match on the indexed id. Indexed/filtered lookup is a range filter
(`id >= lo AND id < hi`, width 200) on that same index. The indexed property is `id` on
CognoDB/Neo4j/Memgraph (a Cypher property index), `node_id` on ArangoDB (a persistent index), and
`node_id` on Dgraph (an `@index(int)` directive).

| Platform | Point p50 | Point p95 | Range p50 | Range p95 |
|---|---|---|---|---|
| CognoDB | 258.2 | 262.5 | 277.5 | 286.5 |
| Neo4j | 5.8 | 48.7 | 6.9 | 36.5 |
| Memgraph | 0.8 | 1.4 | 1.0 | 3.0 |
| ArangoDB (512MB) | 44.8 | 52.8 | 46.0 | 53.5 |
| Dgraph (2GB) | 1.3 | 19.2 | 503.0 | 898.3 |

That Dgraph range-lookup number is real, not a typo — more on it in Section 6.

### Aggregation (p50 / p95, ms)

A single query: total count of `SENT_EMAIL` relationships, timed over 100 repeats.

| Platform | p50 | p95 |
|---|---|---|
| CognoDB | 258.1 | 263.3 |
| Neo4j | 3.0 | 33.5 |
| Memgraph | 85.6 | 105.2 |
| ArangoDB (512MB) | 44.8 | 52.8 |
| Dgraph (2GB) | 1011.2 | 1333.5 |

### Concurrent read/write (80% read / 20% write, 5 seconds per concurrency level)

The write op bumps a `touch_count` property on a random existing node — it doesn't grow the graph, so
it's safe to run repeatedly. "Failures" are write-write conflicts the database itself rejected (for
example, Memgraph's or Dgraph's optimistic concurrency control kicking in), not bugs in the harness —
counted honestly rather than swept under the rug.

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
| CognoDB | 0.5 vCPU / 256MB / 1GB (fixed, managed) | not observable — no metrics endpoint found | not observable |
| Neo4j | 0.5 vCPU / 256MB (Docker) | 99.6–100% | 533 MB |
| Memgraph | 0.5 vCPU / 256MB (Docker) | 43–51% | 469 MB |
| ArangoDB | 0.5 vCPU / 512MB (Docker, deviation) | 31–99%* | 84 MB |
| Dgraph | 0.5 vCPU / 2GB alpha + 0.25 vCPU / 128MB zero (Docker, deviation) | 60–100%* | 58 MB (alpha) |

\* The ArangoDB and Dgraph ranges include readings from before their memory bump as well as after —
shown together on purpose, so the deviation stays visible instead of only showing the number after
the fix made things look fine.

Same logical data — 367,662 edges, 36,692 nodes, nothing but an integer id on each node — and the
on-disk size still ranges 9x between platforms, from 58MB to 533MB. That's a storage-engine and
encoding difference, not a data difference (see Section 6).

**A note on query design:** every hop-depth, lookup, and aggregation query means the same thing
logically on every platform — same predicate, same target — but it's written in each platform's own
query language: Cypher for CognoDB/Neo4j/Memgraph, AQL for ArangoDB, DQL for Dgraph. The actual query
text for each is in `src/workloads/`.

## 6. Analysis

Sharing Cypher across CognoDB, Neo4j, and Memgraph turned out to matter more than I expected going in.
Because the exact same query text and driver code runs against all three, any difference between them
really is coming from the storage engine and how it's deployed — not from one query being written a
little more carefully than another. That's the main reason I'd trust this comparison where it's
saying something about the engines themselves.

Two of the five platforms — ArangoDB and CognoDB — show almost the same latency no matter what query
they're running. ArangoDB sits around 44–54ms and CognoDB around 258–277ms whether it's a 1-hop
traversal or a full aggregation over the whole graph. That flatness is telling you something: each
request is paying a mostly-fixed cost before the query even starts — an HTTP round trip for ArangoDB's
REST-based driver, and real internet latency plus CognoDB's own request handling for CognoDB — and
that fixed cost is big enough to swallow whatever difference the actual query work would otherwise
show. Neo4j, Memgraph, and Dgraph all keep a persistent connection over Bolt or gRPC instead, and you
can see it in their numbers: 1-hop is cheapest, 3-hop costs the most, and point lookup tracks close to
1-hop.

The aggregation query is the clearest example of something architectural showing up in the numbers.
Memgraph and Dgraph are both far slower answering "how many `SENT_EMAIL` edges are there" than they are
at anything else they do — Memgraph jumps to 85.6ms when everything else it runs is under 2ms, and
Dgraph jumps to over a second when everything else it runs is under 6ms. Neo4j answers the same
question in 3ms. My best guess for why: Neo4j keeps a running count per relationship type internally —
a count store — so this kind of query never has to touch the actual relationships at all. Memgraph and
Dgraph look like they're doing a real scan to answer it (Dgraph's query in particular has to compute a
count per node and then sum those before it can return anything). I can't inspect either engine's
internals directly to confirm this, but it's a specific enough guess that someone could go check it,
and it lines up with everything else these two databases do quickly.

Dgraph's range-lookup number — 503ms at the median, 898ms at p95 — is the biggest outlier in this
entire benchmark, about a hundred times its own point-lookup cost and far past anything the other four
platforms show for the same query shape. It's also the exact query type that OOM-killed Dgraph twice
before the 2GB bump. My guess is that its `ge`/`lt` range filter over an indexed integer isn't actually
resolved as a narrow scan the way it would be in a B-tree — something broader is getting touched, a
posting list or similar structure, and that's expensive in both time and memory even though a plain
point lookup on the same index is nearly free. I'd rather write that guess down than either hide the
number or leave it unexplained.

Storage size is the other place where the differences are architectural rather than incidental. Same
data everywhere, but Neo4j and Memgraph — the two largest on disk — both keep write-ahead logs and
native node/relationship formats built for fast random access and durability, not for being small.
ArangoDB and Dgraph both sit on log-structured storage (RocksDB and Badger respectively) with
compression, which favors compactness over that same fixed-size random-access layout. None of this
makes one engine better than another — it's a real tradeoff against the durability and access patterns
each one is designed around — but it does mean a storage-size comparison here is comparing design
choices, not just how efficiently each team implemented the same idea.

The concurrency numbers behave about how you'd expect from something capped at half a CPU core. Every
self-hosted platform's throughput climbs a lot from 1 to 40 concurrent clients — ArangoDB goes from
21.2 to 632.5 ops/sec, roughly 30x — because a single connection barely uses the CPU it's allowed, and
40 of them finally start to saturate it. p95 latency climbs at the same time, which is just queueing
showing up once the core is actually busy — not a surprise, just the expected shape. CognoDB scales
too, from 2.7 to 102.6 ops/sec, but far less dramatically, which fits with the network round trip
already dominating its latency before concurrency even enters the picture. Write conflicts only show
up under real concurrency, and only on Memgraph, ArangoDB, and Dgraph — all three use an
optimistic/MVCC style of concurrency control that rejects a losing writer outright rather than making
it wait. Neo4j had conflicts too, but only three out of 995 operations at the highest concurrency
level, and CognoDB had none at all in this run. That difference is probably about locking granularity
or isolation defaults, but I can't verify that from outside either engine — it's a good question for
someone who can actually see their internals.

## 7. Caveats

- CognoDB's free tier is fixed at 0.5 vCPU / 256MB / 1GB and I couldn't find any metrics endpoint
  that would show actual memory or CPU usage during the run — so its footprint is reported as "not
  observable" rather than guessed at.
- CognoDB's load and query times include real network latency; the other four run on localhost. That
  makes CognoDB's raw numbers look worse in a way that's partly just "it's over the internet," so
  compare throughput and shape more than absolute wall-clock time.
- Dgraph's `alpha` node runs at 2GB for this whole benchmark, not the 256MB every other self-hosted
  platform uses — confirmed necessary by three separate OOM-kills across the load and workload phases
  (Section 2). Its numbers aren't on equal resource footing with the rest, and I've tried to flag that
  everywhere they show up rather than just once.
- ArangoDB also needed a bump, to 512MB, specifically because the query workload (not the load) OOM-
  killed it at 256MB. A smaller deviation than Dgraph's, but still a deviation.
- CognoDB's connection password was typed into a chat session during setup, so I'm treating it as
  exposed. It should be rotated before this environment is used for anything beyond this benchmark.
- The assignment's example connection URI format (`.databases.cognodb.cloud`) didn't match what my
  actual console gave me (`.databases.cognodb.com`) — copy the exact URI from your own console rather
  than the one in the doc.
- Early versions of the 2-hop/3-hop traversal queries had no limit on result size, and that alone was
  enough to OOM-kill ArangoDB and hit a gRPC message-size limit on Dgraph, before I'd changed any
  memory settings. Every platform's 2-hop/3-hop query is now capped at roughly 1000 matched paths — a
  deliberate choice made once this showed up, not something quietly patched over without saying so.
- The concurrency harness originally let an uncaught write-conflict exception kill a worker thread
  outright (I saw this happen on Memgraph: `Cannot resolve conflicting transactions`), which would
  have silently under-reported throughput for whatever was left of that run. It now catches per-
  operation exceptions, counts them as failures, and keeps going for the rest of the timed window.
- The first query each concurrency-harness thread runs is an untimed warm-up. Before I added this, the
  cost of setting up a connection and compiling a query plan was dominating the p95 at low concurrency
  — Neo4j's very first run showed a 4459ms p95 on only 10 total operations, which was clearly that,
  not a real result.
- I ran each metric once rather than repeating it multiple times to characterize variance — given the
  time available, that's a real limitation. Treat every number in Section 5 as one representative
  sample, not a statistically robust distribution. Re-running any `src/workloads/run_*` or
  `src/harness/run_*` script will give you a fresh one.
