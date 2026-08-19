import os

from dotenv import load_dotenv

from src.harness.cypher_rw import run

load_dotenv()


def main():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    auth = (os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "benchmarkpass"))
    print(run("neo4j", uri, auth))


if __name__ == "__main__":
    main()
