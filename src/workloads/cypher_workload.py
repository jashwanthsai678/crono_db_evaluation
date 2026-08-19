"""Shared workload queries for every Cypher/Bolt-compatible platform (CognoDB, Neo4j, Memgraph).

Same rationale as src/common/cypher_loader.py: one implementation covers all three since
they speak the same protocol and dialect.
"""

import time

from neo4j import GraphDatabase

from ..common.percentiles import p50_p95
from ..common.results import write_result
from ..common.sampling import sample_start_ids, sample_ranges

WARMUP = 5

# 2-hop/3-hop counts are capped at 1000 matched paths (via WITH ... LIMIT, which most cost-based
# planners push down into the traversal itself). This email network has hub nodes whose exact-3-hop
# fan-out was observed to exceed 180,000 paths from a single start node - large enough on its own to
# OOM multiple engines during testing (see README section 2/7). Capping is also more representative:
# production traversal queries almost always bound result size rather than materializing everything.
HOP_QUERIES = {
    1: "MATCH (a:Person {id:$id})-[:SENT_EMAIL]->(b) RETURN count(b) AS c",
    2: "MATCH (a:Person {id:$id})-[:SENT_EMAIL]->()-[:SENT_EMAIL]->(b) WITH b LIMIT 1000 RETURN count(b) AS c",
    3: "MATCH (a:Person {id:$id})-[:SENT_EMAIL]->()-[:SENT_EMAIL]->()-[:SENT_EMAIL]->(b) WITH b LIMIT 1000 RETURN count(b) AS c",
}
POINT_LOOKUP_QUERY = "MATCH (p:Person {id:$id}) RETURN p"
RANGE_LOOKUP_QUERY = "MATCH (p:Person) WHERE p.id >= $lo AND p.id < $hi RETURN count(p) AS c"
AGGREGATION_QUERY = "MATCH ()-[r:SENT_EMAIL]->() RETURN count(r) AS c"


def _timed(session, query, params, iterations, warmup=WARMUP):
    for _ in range(warmup):
        session.run(query, **params[0]).consume()

    latencies = []
    for p in params[:iterations]:
        t0 = time.perf_counter()
        session.run(query, **p).consume()
        latencies.append((time.perf_counter() - t0) * 1000)
    return latencies


def run(platform_name, uri, auth):
    start_ids = sample_start_ids()
    ranges = sample_ranges()

    driver = GraphDatabase.driver(uri, auth=auth)
    driver.verify_connectivity()

    result = {"platform": platform_name}
    with driver.session() as session:
        for hop, query in HOP_QUERIES.items():
            params = [{"id": i} for i in start_ids]
            latencies = _timed(session, query, params, len(start_ids))
            p50, p95 = p50_p95(latencies)
            result[f"traversal_{hop}hop_p50_ms"] = p50
            result[f"traversal_{hop}hop_p95_ms"] = p95

        params = [{"id": i} for i in start_ids]
        latencies = _timed(session, POINT_LOOKUP_QUERY, params, len(start_ids))
        p50, p95 = p50_p95(latencies)
        result["point_lookup_p50_ms"] = p50
        result["point_lookup_p95_ms"] = p95

        params = [{"lo": lo, "hi": hi} for lo, hi in ranges]
        latencies = _timed(session, RANGE_LOOKUP_QUERY, params, len(ranges))
        p50, p95 = p50_p95(latencies)
        result["indexed_range_lookup_p50_ms"] = p50
        result["indexed_range_lookup_p95_ms"] = p95

        params = [{} for _ in range(100)]
        latencies = _timed(session, AGGREGATION_QUERY, params, 100)
        p50, p95 = p50_p95(latencies)
        result["aggregation_p50_ms"] = p50
        result["aggregation_p95_ms"] = p95

    driver.close()
    write_result(f"workload_{platform_name}", result)
    return result
