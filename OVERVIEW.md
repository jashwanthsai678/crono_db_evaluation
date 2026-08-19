# Overview — CognoDB Cloud Graph Benchmark

*A quick note before anything else: I used AI (Claude) to help build this — designing the test
scripts, debugging problems as they came up, and drafting this documentation. I directed every
decision, ran the tests, read the evidence, and can explain and defend everything below. The
detailed technical README (`README.md`) has the full tables, raw numbers, and query text; this
document is the plain-English walkthrough of what I did, why, and what it found.*

## What I was asked to do

Wexa AI's assignment was to take their managed graph database, CognoDB Cloud, and compare it
honestly against at least four other graph databases — same data, same queries, same resource
limits, fully automated, with every caveat written down rather than hidden. The grading isn't about
which database "wins" — it's about whether the comparison was actually fair, whether it's
reproducible, and whether I can explain what the numbers mean.

## Which databases I picked, and why

I chose **Neo4j** and **Memgraph** because they happen to speak the exact same query language and
protocol as CognoDB (Cypher over Bolt). That means I could run identical query code against three of
the five platforms — so any difference in their numbers is genuinely coming from the database
itself, not from me writing one query more carefully than another. Then I added **ArangoDB** and
**Dgraph** for real variety — different query languages, different underlying engines — while
staying away from options that would have needed a much bigger, multi-part setup (like JanusGraph,
which needs two extra services just to run) given the tight time window.

## Making sure the comparison was actually fair

CognoDB's free plan gives you a fixed, small amount of resources: half a CPU core, 256MB of memory,
1GB of disk. The obvious approach is to just give every other database the same limit and call it
fair. I didn't stop there — I actually tested whether each database could survive at that limit,
both while loading the data and while running the actual test queries, and watched for real crashes
(not just "memory looks high"), using Docker's own crash-detection flag.

Two databases couldn't survive on the same tiny amount of resources as everyone else, and I found
that out by actually pushing them, not by guessing:

- **ArangoDB** loaded the data fine, but crashed about six seconds into running the test queries. I
  gave it double the memory (512MB) and it was fine after that.
- **Dgraph** was much harder. It crashed three separate times — once just setting up its schema,
  once partway through loading the data, and once partway through the test queries — before it
  finally became stable at eight times the original memory limit (2GB).

I kept both in the comparison, because leaving them out would tell you less than showing exactly
where they break and how much they actually need. But it's important to be upfront: their numbers
aren't on a level playing field with the other three, and I've flagged that everywhere it matters.

**A mistake that turned into a useful finding:** early on, my loading script tried to wipe old data
before loading fresh data, so I could re-run it while I was still building it. That wiping step —
not the actual loading — is what caused most of the crashes above. Deleting a lot of existing data
can actually use more memory than adding it in the first place. Two databases failed in very
different ways when this happened: Neo4j got stuck completely — still technically "running" but not
doing anything, with no outward sign anything was wrong. Memgraph, on the other hand, noticed it was
running low on memory and just returned a clean error, no damage done. I fixed this by having every
loading script simply refuse to run if the database isn't already empty, instead of trying to clean
up mid-flight.

## The data I used

I used a real, public dataset from Stanford's SNAP collection: the Enron email network — about
36,700 people and 367,700 email connections between them. It's a well-known dataset, sized right in
the range the assignment asked for, and I bundled a copy directly in the project so anyone
re-running this doesn't depend on an external website staying online.

## What I actually measured

For every database, I measured:
- **How fast it loads the data** (nodes and edges per second)
- **How fast it answers "who's connected 1, 2, or 3 steps away"** (a core graph question)
- **How fast it looks up one specific record**, and **how fast it filters a range of records**
- **How fast it counts things** (a basic aggregation query)
- **How it holds up under multiple people hitting it at once** (1, 10, and 40 simultaneous users,
  mixing reads and writes)
- **How much space it uses on disk and in memory**

Every test ran the same query, on the same data, at least 100 times, so the results (reported as
"typical" and "worst-case-ish" numbers, technically called p50 and p95) are stable rather than a
one-off fluke.

## What I found

**Databases that keep an open connection (Neo4j, Memgraph, Dgraph) behave the way you'd expect** —
simple questions answer fast, harder ones take a bit longer. **Two databases (ArangoDB and CognoDB)
answered almost every question at roughly the same speed regardless of how hard it was** — around
45-55ms for ArangoDB, and 260-280ms for CognoDB. That's a sign the time is mostly being spent just on
the back-and-forth of the request itself (a web-style request for ArangoDB, real internet travel
time for CognoDB), rather than on the actual work the database is doing.

**Counting all the email connections in the graph produced the most surprising numbers.** Neo4j
answered it in 3 milliseconds — almost certainly because it keeps a running tally in the background
rather than counting from scratch every time. Memgraph took 86ms and Dgraph took over a full second
for the exact same logical question, suggesting they're doing real work to count rather than reading
a pre-kept number.

**Dgraph had one especially strange result:** looking up a range of records took over 500
milliseconds — a hundred times slower than looking up a single record on the very same database.
That's also the exact kind of question that crashed it twice before I gave it more memory, so
something about how it handles that particular type of query is expensive.

**Storage size varied enormously for the exact same data** — from 58MB up to 533MB. That's not a
difference in the data itself; it's a difference in how each database chooses to store things on
disk (some prioritize being small, others prioritize being fast to write to).

**Under heavier concurrent load, throughput went up for every database, as expected**, since a
single connection barely uses the small amount of CPU each one was allowed. A few write conflicts
appeared under the heaviest load on three of the five databases — expected behavior for how they
handle multiple people trying to change the same thing at once, not a bug.

## Honest limitations

- CognoDB doesn't expose any way to see its actual memory/CPU usage from outside, so its resource
  footprint is reported as "can't observe this" rather than guessed.
- CognoDB's numbers include real internet travel time, since it's a cloud service; the other four ran
  on my own machine, so that's not a perfectly even comparison on raw speed, only on relative shape.
- Two databases (ArangoDB, Dgraph) needed more memory than the others to survive at all — clearly
  marked everywhere their numbers show up, not just once.
- I ran each test once rather than many times to check for run-to-run variation, given the time
  available — so treat every number as one solid sample, not a guaranteed-stable average.
- A couple of real bugs came up and got fixed while building this (an unbounded query that could
  crash a database by asking for too much at once, and a concurrency test that could silently lose
  track of failed operations) — both are described in detail, with the fix, in the technical README.

Full details, exact numbers, and the actual query code are in `README.md` and the `src/` folder.
