import os

import pydgraph
from dotenv import load_dotenv

from src.harness.concurrent_rw import run

load_dotenv()

READ_QUERY = """
query q($id: string) {
  q(func: eq(node_id, $id)) { uid node_id }
}
"""


def main():
    grpc_addr = os.environ.get("DGRAPH_GRPC", "localhost:9080")

    def connect():
        stub = pydgraph.DgraphClientStub(
            grpc_addr, options=[("grpc.max_receive_message_length", 32 * 1024 * 1024)]
        )
        return pydgraph.DgraphClient(stub)

    def read(client, node_id):
        client.txn(read_only=True).query(READ_QUERY, variables={"$id": str(node_id)})

    def write(client, node_id):
        txn = client.txn()
        try:
            query = "{ q(func: eq(node_id, %d)) { v as uid } }" % node_id
            mutation = txn.create_mutation(set_nquads='uid(v) <touch_count> "1" .')
            request = txn.create_request(query=query, mutations=[mutation], commit_now=True)
            txn.do_request(request)
        finally:
            txn.discard()

    print(run("dgraph", connect, read, write))


if __name__ == "__main__":
    main()
