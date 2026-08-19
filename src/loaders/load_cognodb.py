"""Data-loading benchmark: CognoDB Cloud (managed, free c0 tier)."""

import os

from dotenv import load_dotenv

from src.common.cypher_loader import run

load_dotenv()


def main():
    uri = os.environ["COGNODB_URI"]
    auth = (os.environ["COGNODB_USER"], os.environ["COGNODB_PASSWORD"])
    result = run("cognodb", uri, auth)
    print(result)


if __name__ == "__main__":
    main()
