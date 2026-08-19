"""Data-loading benchmark: ArangoDB (self-hosted, Docker, 0.5 vCPU / 256MB capped)."""

import os
import time

from arango import ArangoClient
from dotenv import load_dotenv

from src.common.dataset import load_edges
from src.common.results import write_result

load_dotenv()

NODE_BATCH = 5000
EDGE_BATCH = 5000


def main():
    url = os.environ.get("ARANGO_URL", "http://localhost:8529")
    user = os.environ.get("ARANGO_USER", "root")
    password = os.environ.get("ARANGO_PASSWORD", "benchmarkpass")
    db_name = os.environ.get("ARANGO_DB", "benchmark")

    nodes, edges = load_edges()

    client = ArangoClient(hosts=url)
    sys_db = client.db("_system", username=user, password=password)
    if not sys_db.has_database(db_name):
        sys_db.create_database(db_name)
    db = client.db(db_name, username=user, password=password)

    # Clean slate so repeated runs measure a real cold load, not an upsert into existing data.
    if db.has_collection("Person"):
        db.delete_collection("Person")
    if db.has_collection("SENT_EMAIL"):
        db.delete_collection("SENT_EMAIL")
    person = db.create_collection("Person")
    person.add_index({"type": "persistent", "fields": ["node_id"], "unique": True})
    sent_email = db.create_collection("SENT_EMAIL", edge=True)

    t0 = time.time()
    docs = [{"_key": str(n), "node_id": n} for n in nodes]
    for i in range(0, len(docs), NODE_BATCH):
        person.insert_many(docs[i:i + NODE_BATCH])
    t_nodes = time.time()

    edge_docs = [{"_from": f"Person/{a}", "_to": f"Person/{b}"} for a, b in edges]
    for i in range(0, len(edge_docs), EDGE_BATCH):
        sent_email.insert_many(edge_docs[i:i + EDGE_BATCH])
    t_edges = time.time()

    node_seconds = t_nodes - t0
    edge_seconds = t_edges - t_nodes
    result = {
        "platform": "arangodb",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_load_seconds": round(node_seconds, 2),
        "edge_load_seconds": round(edge_seconds, 2),
        "total_load_seconds": round(t_edges - t0, 2),
        "nodes_per_second": round(len(nodes) / node_seconds, 1) if node_seconds > 0 else None,
        "edges_per_second": round(len(edges) / edge_seconds, 1) if edge_seconds > 0 else None,
    }
    write_result("load_arangodb", result)
    print(result)


if __name__ == "__main__":
    main()
