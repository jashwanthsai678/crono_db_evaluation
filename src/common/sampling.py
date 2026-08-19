"""Deterministic sampling shared by every workload runner.

Fixed seed so every platform is queried against the exact same start nodes and
ranges - required by the "same logical queries" fairness rule, not just "same dataset".
"""

import random

from .dataset import load_edges

SEED = 42
SAMPLE_SIZE = 100
RANGE_WIDTH = 200


def sample_start_ids():
    nodes, _ = load_edges()
    rng = random.Random(SEED)
    return rng.sample(nodes, SAMPLE_SIZE)


def sample_ranges():
    nodes, _ = load_edges()
    rng = random.Random(SEED + 1)
    lo_max = max(nodes) - RANGE_WIDTH
    los = [rng.randint(0, lo_max) for _ in range(SAMPLE_SIZE)]
    return [(lo, lo + RANGE_WIDTH) for lo in los]
