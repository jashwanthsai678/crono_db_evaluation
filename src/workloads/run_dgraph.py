import os
import time

import pydgraph
from dotenv import load_dotenv

from src.common.percentiles import p50_p95
from src.common.results import write_result
from src.common.sampling import sample_start_ids, sample_ranges

load_dotenv()

WARMUP = 5

# 2-hop/3-hop fan-out capped via `first:` at each nested level (32*32 ~= 1024 worst case at the
# deepest level), matching the ~1000-match cap used for the other platforms - see
# cypher_workload.py's HOP_QUERIES comment for why: this email network's exact-3-hop fan-out was
# observed to exceed 180,000 paths from a single start node, large enough on its own to OOM
# multiple engines during testing (see README section 2/7).
HOP_QUERIES = {
    1: """
    query q($id: string) {
      q(func: eq(node_id, $id)) { sent_email { uid } }
    }
    """,
    2: """
    query q($id: string) {
      q(func: eq(node_id, $id)) { sent_email { sent_email (first: 32) { uid } } }
    }
    """,
    3: """
    query q($id: string) {
      q(func: eq(node_id, $id)) { sent_email { sent_email (first: 32) { sent_email (first: 32) { uid } } } }
    }
    """,
}
POINT_LOOKUP_QUERY = """
query q($id: string) {
  q(func: eq(node_id, $id)) { uid node_id }
}
"""
RANGE_LOOKUP_QUERY = """
query q($lo: string, $hi: string) {
  q(func: ge(node_id, $lo)) @filter(lt(node_id, $hi)) { uid }
}
"""
AGGREGATION_QUERY = """
{
  var(func: has(sent_email)) {
    c as count(sent_email)
  }
  total() {
    s: sum(val(c))
  }
}
"""


def _timed(client, query, params, iterations, warmup=WARMUP):
    for _ in range(warmup):
        client.txn(read_only=True).query(query, variables=params[0])

    latencies = []
    for p in params[:iterations]:
        t0 = time.perf_counter()
        client.txn(read_only=True).query(query, variables=p)
        latencies.append((time.perf_counter() - t0) * 1000)
    return latencies


def main():
    grpc_addr = os.environ.get("DGRAPH_GRPC", "localhost:9080")
    # The dense email network's 3-hop fan-out returns responses well over pydgraph's default
    # 4MB gRPC max receive size (confirmed via RESOURCE_EXHAUSTED) - raised to 32MB.
    client_stub = pydgraph.DgraphClientStub(
        grpc_addr, options=[("grpc.max_receive_message_length", 32 * 1024 * 1024)]
    )
    client = pydgraph.DgraphClient(client_stub)

    start_ids = sample_start_ids()
    ranges = sample_ranges()

    result = {"platform": "dgraph", "resource_deviation": "alpha at 2GB for workload queries, not the 256MB baseline (1GB sufficed for loading only)"}

    for hop, query in HOP_QUERIES.items():
        params = [{"$id": str(i)} for i in start_ids]
        latencies = _timed(client, query, params, len(start_ids))
        p50, p95 = p50_p95(latencies)
        result[f"traversal_{hop}hop_p50_ms"] = p50
        result[f"traversal_{hop}hop_p95_ms"] = p95

    params = [{"$id": str(i)} for i in start_ids]
    latencies = _timed(client, POINT_LOOKUP_QUERY, params, len(start_ids))
    p50, p95 = p50_p95(latencies)
    result["point_lookup_p50_ms"] = p50
    result["point_lookup_p95_ms"] = p95

    params = [{"$lo": str(lo), "$hi": str(hi)} for lo, hi in ranges]
    latencies = _timed(client, RANGE_LOOKUP_QUERY, params, len(ranges))
    p50, p95 = p50_p95(latencies)
    result["indexed_range_lookup_p50_ms"] = p50
    result["indexed_range_lookup_p95_ms"] = p95

    params = [{} for _ in range(100)]
    latencies = _timed(client, AGGREGATION_QUERY, params, 100)
    p50, p95 = p50_p95(latencies)
    result["aggregation_p50_ms"] = p50
    result["aggregation_p95_ms"] = p95

    write_result("workload_dgraph", result)
    print(result)


if __name__ == "__main__":
    main()
