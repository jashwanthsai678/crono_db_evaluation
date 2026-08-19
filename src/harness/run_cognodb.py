import os

from dotenv import load_dotenv

from src.harness.cypher_rw import run

load_dotenv()


def main():
    uri = os.environ["COGNODB_URI"]
    auth = (os.environ["COGNODB_USER"], os.environ["COGNODB_PASSWORD"])
    print(run("cognodb", uri, auth))


if __name__ == "__main__":
    main()
