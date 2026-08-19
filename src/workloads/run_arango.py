import os
import time

from arango import ArangoClient
from dotenv import load_dotenv

from src.common.percentiles import p50_p95
from src.common.results import write_result
from src.common.sampling import sample_start_ids, sample_ranges

load_dotenv()

WARMUP = 5

# Capped at 1000 matches - see cypher_workload.py's HOP_QUERIES comment for why (this email
# network's exact-3-hop fan-out was observed to exceed 180,000 paths from a single start node,
# large enough on its own to OOM multiple engines during testing; see README section 2/7).
HOP_QUERIES = {
    1: "FOR v IN 1..1 OUTBOUND @start SENT_EMAIL COLLECT WITH COUNT INTO c RETURN c",
    2: "FOR v IN 2..2 OUTBOUND @start SENT_EMAIL LIMIT 1000 COLLECT WITH COUNT INTO c RETURN c",
    3: "FOR v IN 3..3 OUTBOUND @start SENT_EMAIL LIMIT 1000 COLLECT WITH COUNT INTO c RETURN c",
}
POINT_LOOKUP_QUERY = "FOR p IN Person FILTER p.node_id == @id RETURN p"
RANGE_LOOKUP_QUERY = "FOR p IN Person FILTER p.node_id >= @lo AND p.node_id < @hi COLLECT WITH COUNT INTO c RETURN c"
AGGREGATION_QUERY = "RETURN LENGTH(SENT_EMAIL)"


def _timed(aql, query, params, iterations, warmup=WARMUP):
    for _ in range(warmup):
        list(aql.execute(query, bind_vars=params[0]))

    latencies = []
    for p in params[:iterations]:
        t0 = time.perf_counter()
        list(aql.execute(query, bind_vars=p))
        latencies.append((time.perf_counter() - t0) * 1000)
    return latencies


def main():
    url = os.environ.get("ARANGO_URL", "http://localhost:8529")
    user = os.environ.get("ARANGO_USER", "root")
    password = os.environ.get("ARANGO_PASSWORD", "benchmarkpass")
    db_name = os.environ.get("ARANGO_DB", "benchmark")

    client = ArangoClient(hosts=url)
    db = client.db(db_name, username=user, password=password)
    aql = db.aql

    start_ids = sample_start_ids()
    ranges = sample_ranges()

    result = {"platform": "arangodb"}

    for hop, query in HOP_QUERIES.items():
        params = [{"start": f"Person/{i}"} for i in start_ids]
        latencies = _timed(aql, query, params, len(start_ids))
        p50, p95 = p50_p95(latencies)
        result[f"traversal_{hop}hop_p50_ms"] = p50
        result[f"traversal_{hop}hop_p95_ms"] = p95

    params = [{"id": i} for i in start_ids]
    latencies = _timed(aql, POINT_LOOKUP_QUERY, params, len(start_ids))
    p50, p95 = p50_p95(latencies)
    result["point_lookup_p50_ms"] = p50
    result["point_lookup_p95_ms"] = p95

    params = [{"lo": lo, "hi": hi} for lo, hi in ranges]
    latencies = _timed(aql, RANGE_LOOKUP_QUERY, params, len(ranges))
    p50, p95 = p50_p95(latencies)
    result["indexed_range_lookup_p50_ms"] = p50
    result["indexed_range_lookup_p95_ms"] = p95

    params = [{} for _ in range(100)]
    latencies = _timed(aql, AGGREGATION_QUERY, params, 100)
    p50, p95 = p50_p95(latencies)
    result["aggregation_p50_ms"] = p50
    result["aggregation_p95_ms"] = p95

    write_result("workload_arangodb", result)
    print(result)


if __name__ == "__main__":
    main()
