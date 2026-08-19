"""Read/write callables for the concurrent harness, shared by CognoDB/Neo4j/Memgraph."""

from neo4j import GraphDatabase

from .concurrent_rw import run as run_sweep

POINT_LOOKUP_QUERY = "MATCH (p:Person {id:$id}) RETURN p"
WRITE_QUERY = "MATCH (p:Person {id:$id}) SET p.touch_count = coalesce(p.touch_count, 0) + 1"


class _Conn:
    def __init__(self, uri, auth):
        self.driver = GraphDatabase.driver(uri, auth=auth)
        self.session = self.driver.session()

    def close(self):
        self.session.close()
        self.driver.close()


def run(platform_name, uri, auth):
    def connect():
        return _Conn(uri, auth)

    def read(conn, node_id):
        conn.session.run(POINT_LOOKUP_QUERY, id=node_id).consume()

    def write(conn, node_id):
        conn.session.run(WRITE_QUERY, id=node_id).consume()

    return run_sweep(platform_name, connect, read, write)
