import os

from arango import ArangoClient
from dotenv import load_dotenv

from src.harness.concurrent_rw import run

load_dotenv()

READ_QUERY = "FOR p IN Person FILTER p.node_id == @id RETURN p"
WRITE_QUERY = """
LET doc = DOCUMENT(CONCAT('Person/', @id))
UPDATE doc WITH {touch_count: (doc.touch_count == null ? 1 : doc.touch_count + 1)} IN Person
"""


def main():
    url = os.environ.get("ARANGO_URL", "http://localhost:8529")
    user = os.environ.get("ARANGO_USER", "root")
    password = os.environ.get("ARANGO_PASSWORD", "benchmarkpass")
    db_name = os.environ.get("ARANGO_DB", "benchmark")

    def connect():
        client = ArangoClient(hosts=url)
        return client.db(db_name, username=user, password=password)

    def read(db, node_id):
        list(db.aql.execute(READ_QUERY, bind_vars={"id": node_id}))

    def write(db, node_id):
        list(db.aql.execute(WRITE_QUERY, bind_vars={"id": node_id}))

    print(run("arangodb", connect, read, write))


if __name__ == "__main__":
    main()
