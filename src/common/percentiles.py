"""Latency percentile helper shared by every workload runner."""

import math


def p50_p95(latencies_ms):
    if not latencies_ms:
        return None, None
    s = sorted(latencies_ms)
    n = len(s)

    def pct(p):
        idx = min(n - 1, max(0, math.ceil(p * n) - 1))
        return s[idx]

    return round(pct(0.50), 2), round(pct(0.95), 2)
