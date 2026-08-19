"""Shared result-writing so every loader/workload emits the same JSON shape into results/."""

import json
import os

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "results")


def write_result(name, payload):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"{name}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"wrote {path}")
