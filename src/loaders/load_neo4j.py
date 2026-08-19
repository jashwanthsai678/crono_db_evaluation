"""Data-loading benchmark: Neo4j (self-hosted, Docker, 0.5 vCPU / 256MB capped)."""

import os

from dotenv import load_dotenv

from src.common.cypher_loader import run

load_dotenv()


def main():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    auth = (os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "benchmarkpass"))
    result = run("neo4j", uri, auth)
    print(result)


if __name__ == "__main__":
    main()
