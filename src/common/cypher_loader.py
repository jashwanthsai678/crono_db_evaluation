"""Shared loader for every Cypher/Bolt-compatible platform (CognoDB, Neo4j, Memgraph).

They speak the same protocol and dialect, so one implementation covers all three -
only the connection details differ per platform script in src/loaders/.
"""

import time

from neo4j import GraphDatabase

from .dataset import load_edges
from .results import write_result

NODE_BATCH = 1000
EDGE_BATCH = 1000


class NotEmptyError(RuntimeError):
    pass


def run(platform_name, uri, auth, index_create_stmt="CREATE INDEX person_id IF NOT EXISTS FOR (p:Person) ON (p.id)"):
    nodes, edges = load_edges()
    driver = GraphDatabase.driver(uri, auth=auth)
    driver.verify_connectivity()

    with driver.session() as session:
        # Data-loading throughput is only a meaningful number against a genuinely empty database -
        # NOT after an in-place delete-all. A prior version of this loader tried to clear leftover
        # data itself; under the 256MB cap that delete was observed to time out Neo4j's connection
        # and push Memgraph over its internal --memory-limit (deleting hundreds of thousands of
        # rows can cost more memory than the original insert). So this now refuses to run against
        # a non-empty database rather than silently paying that cost - recreate the container with
        # a fresh volume between measured runs instead (see README section 4).
        existing = session.run("MATCH (n:Person) RETURN count(n) AS c").single()["c"]
        if existing > 0:
            raise NotEmptyError(
                f"{platform_name} already has {existing} Person nodes - recreate its container/volume "
                "for a fresh load before re-running this benchmark."
            )
        session.run(index_create_stmt)

        t0 = time.time()
        for i in range(0, len(nodes), NODE_BATCH):
            chunk = nodes[i:i + NODE_BATCH]
            session.run("UNWIND $ids AS id CREATE (:Person {id: id})", ids=chunk)
        t_nodes = time.time()

        for i in range(0, len(edges), EDGE_BATCH):
            chunk = edges[i:i + EDGE_BATCH]
            session.run(
                """
                UNWIND $rows AS row
                MATCH (a:Person {id: row[0]}), (b:Person {id: row[1]})
                CREATE (a)-[:SENT_EMAIL]->(b)
                """,
                rows=[[a, b] for a, b in chunk],
            )
        t_edges = time.time()

    driver.close()

    node_seconds = t_nodes - t0
    edge_seconds = t_edges - t_nodes
    total_seconds = t_edges - t0
    result = {
        "platform": platform_name,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_load_seconds": round(node_seconds, 2),
        "edge_load_seconds": round(edge_seconds, 2),
        "total_load_seconds": round(total_seconds, 2),
        "nodes_per_second": round(len(nodes) / node_seconds, 1) if node_seconds > 0 else None,
        "edges_per_second": round(len(edges) / edge_seconds, 1) if edge_seconds > 0 else None,
    }
    write_result(f"load_{platform_name}", result)
    return result
