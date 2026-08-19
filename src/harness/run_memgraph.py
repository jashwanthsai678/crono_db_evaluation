import os

from dotenv import load_dotenv

from src.harness.cypher_rw import run

load_dotenv()


def main():
    uri = os.environ.get("MEMGRAPH_URI", "bolt://localhost:7688")
    auth = (os.environ.get("MEMGRAPH_USER", ""), os.environ.get("MEMGRAPH_PASSWORD", ""))
    print(run("memgraph", uri, auth))


if __name__ == "__main__":
    main()
