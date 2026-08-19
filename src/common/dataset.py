"""Shared dataset loading for the SNAP email-Enron graph used by every platform loader.

Kept in one place so every loader parses the identical node/edge set the same way -
central to the "same dataset, same logical queries" fairness rule in the assignment.
"""

import gzip
import os
import shutil

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw")
DATA_PATH = os.path.join(DATA_DIR, "email-Enron.txt")
DATA_GZ_PATH = os.path.join(DATA_DIR, "email-Enron.txt.gz")


def _ensure_extracted():
    if os.path.exists(DATA_PATH):
        return
    # The .gz is committed to the repo (source: https://snap.stanford.edu/data/email-Enron.html);
    # the .txt is regenerated from it here rather than committing an already-decompressed 4MB
    # duplicate, and rather than depending on the SNAP mirror being reachable at benchmark time.
    with gzip.open(DATA_GZ_PATH, "rb") as src, open(DATA_PATH, "wb") as dst:
        shutil.copyfileobj(src, dst)


def load_edges(path=DATA_PATH):
    """Returns (nodes: sorted list[int], edges: list[tuple[int, int]])."""
    _ensure_extracted()
    nodes = set()
    edges = []
    with open(path) as f:
        for line in f:
            if line.startswith("#"):
                continue
            a, b = line.split()
            a, b = int(a), int(b)
            nodes.add(a)
            nodes.add(b)
            edges.append((a, b))
    return sorted(nodes), edges
