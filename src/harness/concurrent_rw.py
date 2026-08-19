"""Generic concurrent read/write harness, shared across all five platforms.

Each platform script supplies connect/read/write callables; this module supplies the
concurrency sweep, timing, and aggregation so that part of the methodology is identical
everywhere rather than five separate implementations that could subtly differ.
"""

import random
import threading
import time

from ..common.percentiles import p50_p95
from ..common.results import write_result
from ..common.sampling import sample_start_ids

CONCURRENCY_LEVELS = [1, 10, 40]
DURATION_SEC = 5
READ_WRITE_RATIO = 0.8  # 80% reads, 20% writes - a common OLTP-ish mix, documented in README


def _worker(connect_fn, read_fn, write_fn, ids, stop_at, rng_seed, out_latencies, out_counts):
    rng = random.Random(rng_seed)
    conn = connect_fn()
    reads = 0
    writes = 0
    failures = 0
    try:
        # Warm up the connection/query plan before the timed window starts - an untimed cold
        # first-query was observed dominating the p95 at low concurrency (few samples, one of
        # which pays connection + query-plan setup cost).
        try:
            read_fn(conn, ids[0])
        except Exception:
            pass

        while time.perf_counter() < stop_at:
            node_id = rng.choice(ids)
            is_read = rng.random() < READ_WRITE_RATIO
            t0 = time.perf_counter()
            try:
                if is_read:
                    read_fn(conn, node_id)
                    reads += 1
                else:
                    write_fn(conn, node_id)
                    writes += 1
                out_latencies.append((time.perf_counter() - t0) * 1000)
            except Exception:
                # Concurrent writers hitting a real write-write conflict (observed on Memgraph:
                # "Cannot resolve conflicting transactions") is an expected, meaningful outcome of
                # a concurrency test, not a harness bug - counted rather than left to kill the
                # worker thread and silently under-report throughput for the rest of the window.
                failures += 1
    finally:
        close = getattr(conn, "close", None)
        if callable(close):
            close()
    out_counts["reads"] += reads
    out_counts["writes"] += writes
    out_counts["failures"] += failures


def run(platform_name, connect_fn, read_fn, write_fn):
    ids = sample_start_ids()
    result = {"platform": platform_name, "read_write_ratio": READ_WRITE_RATIO, "duration_sec": DURATION_SEC, "sweep": {}}

    for concurrency in CONCURRENCY_LEVELS:
        latencies = []
        counts = {"reads": 0, "writes": 0, "failures": 0}
        lock_latencies = threading.Lock()

        def guarded_worker(seed):
            local_latencies = []
            _worker(connect_fn, read_fn, write_fn, ids, stop_at, seed, local_latencies, counts)
            with lock_latencies:
                latencies.extend(local_latencies)

        stop_at = time.perf_counter() + DURATION_SEC
        threads = [threading.Thread(target=guarded_worker, args=(i,)) for i in range(concurrency)]
        t0 = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.perf_counter() - t0

        total_ops = counts["reads"] + counts["writes"]
        p50, p95 = p50_p95(latencies)
        result["sweep"][str(concurrency)] = {
            "total_ops": total_ops,
            "reads": counts["reads"],
            "writes": counts["writes"],
            "failures": counts["failures"],
            "ops_per_sec": round(total_ops / wall, 1) if wall > 0 else None,
            "latency_p50_ms": p50,
            "latency_p95_ms": p95,
        }

    write_result(f"concurrency_{platform_name}", result)
    return result
