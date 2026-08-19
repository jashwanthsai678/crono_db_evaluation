"""Data-loading benchmark: Memgraph (self-hosted, Docker, 0.5 vCPU / 256MB capped)."""

import os

from dotenv import load_dotenv

from src.common.cypher_loader import run

load_dotenv()


def main():
    uri = os.environ.get("MEMGRAPH_URI", "bolt://localhost:7688")
    # Memgraph's default Community image runs without auth unless explicitly configured.
    auth = (os.environ.get("MEMGRAPH_USER", ""), os.environ.get("MEMGRAPH_PASSWORD", ""))
    result = run("memgraph", uri, auth, index_create_stmt="CREATE INDEX ON :Person(id)")
    print(result)


if __name__ == "__main__":
    main()
