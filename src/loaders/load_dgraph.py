"""Data-loading benchmark: Dgraph (self-hosted, Docker; zero 0.25vCPU/128MB, alpha 0.5vCPU/2GB).

Resource note: alpha is intentionally NOT at the 256MB baseline the other four platforms use.
It was confirmed OOM-killed at 256MB (during schema Alter, before any data), again at 512MB
(partway through node loading), and again at 1GB (partway through the workload's indexed-range
query, after loading had already succeeded at that tier) - see README.md section 2 for the full,
evidence-backed writeup. It runs here at 2GB, the smallest tier found to survive both the load and
the full query workload; loading alone would have fit in 1GB, but the container runs at one
consistent tier across both phases rather than being resized between them.

Reset note: `drop_all` was one of the operations observed OOM-killing alpha at 256MB, so this
loader does NOT call it as a safety net - a clean run instead means recreating alpha's container
+ volume first:
    docker compose -f docker/docker-compose.yml rm -sf dgraph-alpha
    docker volume rm docker_dgraph_alpha_data
    docker compose -f docker/docker-compose.yml up -d dgraph-alpha
"""

import json
import os
import time

import pydgraph
from dotenv import load_dotenv

from src.common.dataset import load_edges
from src.common.results import write_result

load_dotenv()

NODE_BATCH = 1000
EDGE_BATCH = 1000


def main():
    grpc_addr = os.environ.get("DGRAPH_GRPC", "localhost:9080")
    nodes, edges = load_edges()

    client_stub = pydgraph.DgraphClientStub(grpc_addr)
    client = pydgraph.DgraphClient(client_stub)

    schema = """
    node_id: int @index(int) .
    sent_email: [uid] @reverse .
    """
    client.alter(pydgraph.Operation(schema=schema))

    t0 = time.time()
    for i in range(0, len(nodes), NODE_BATCH):
        chunk = nodes[i:i + NODE_BATCH]
        txn = client.txn()
        try:
            mutation = [{"node_id": n, "dgraph.type": "Person"} for n in chunk]
            txn.mutate(set_obj=mutation)
            txn.commit()
        finally:
            txn.discard()
    t_nodes = time.time()

    # Resolve node_id -> uid once, in a single read-only query (dataset is small enough).
    res = client.txn(read_only=True).query("{ q(func: has(node_id)) { uid node_id } }")
    id_to_uid = {row["node_id"]: row["uid"] for row in json.loads(res.json)["q"]}

    for i in range(0, len(edges), EDGE_BATCH):
        chunk = edges[i:i + EDGE_BATCH]
        txn = client.txn()
        try:
            mutation = [
                {"uid": id_to_uid[a], "sent_email": [{"uid": id_to_uid[b]}]}
                for a, b in chunk
            ]
            txn.mutate(set_obj=mutation)
            txn.commit()
        finally:
            txn.discard()
    t_edges = time.time()

    node_seconds = t_nodes - t0
    edge_seconds = t_edges - t_nodes
    result = {
        "platform": "dgraph",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_load_seconds": round(node_seconds, 2),
        "edge_load_seconds": round(edge_seconds, 2),
        "total_load_seconds": round(t_edges - t0, 2),
        "nodes_per_second": round(len(nodes) / node_seconds, 1) if node_seconds > 0 else None,
        "edges_per_second": round(len(edges) / edge_seconds, 1) if edge_seconds > 0 else None,
        "resource_deviation": "alpha capped at 2GB, not the 256MB baseline - see README section 2",
    }
    write_result("load_dgraph", result)
    print(result)


if __name__ == "__main__":
    main()
