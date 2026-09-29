#!/usr/bin/env python3
"""Summarize the 8-round sweep for task_2999.

    python3 workspace/summarize.py

Reads workspace/implementation/results.{1..8}.json and prints, per round, the
pass/total counts plus the UNION of failing tests across all rounds (a test that
fails in only one round is still a failure — that IS the flakiness signal).

Schema note: the runner writes `tests[].status` and `tests[].error_message`.
It does NOT use pytest's `outcome`/`message` keys — a summarizer keyed on
"outcome" silently prints zero failures next to `passed < total`. As a guard,
this script cross-checks the size of the per-round failure list against
(total - passed) and shouts if they disagree.
"""
import glob
import json
import os
import re
from collections import defaultdict

IMPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "implementation")

union = defaultdict(list)   # test id -> [(round, status, error_message)]
first_err = {}

paths = sorted(glob.glob(os.path.join(IMPL, "results.*.json")),
               key=lambda p: int(re.search(r"results\.(\d+)\.json", p).group(1)))
if not paths:
    raise SystemExit("NO results.*.json FOUND — the sweep did not run (or died at t=0). "
                     "Check that start.sh exists and that sweep.sh was launched under setsid.")

for path in paths:
    rnd = int(re.search(r"results\.(\d+)\.json", path).group(1))
    with open(path) as fh:
        data = json.load(fh)
    tests = data.get("tests", [])
    passed = sum(1 for t in tests if t.get("status") == "passed")
    total = data.get("total", len(tests))
    reported_passed = data.get("passed", passed)
    fails = [t for t in tests if t.get("status") not in ("passed", None)]
    for t in fails:
        tid = t.get("test_id") or t.get("name") or t.get("nodeid") or "<unknown>"
        union[tid].append((rnd, t.get("status"), (t.get("error_message") or "")[:400]))
        first_err.setdefault(tid, t.get("error_message") or "")
    flag = ""
    if total - reported_passed != len(fails):
        flag = (f"   <<< KEY-SCHEMA WARNING: total-passed={total - reported_passed} "
                f"but only {len(fails)} non-passed entries found; check the json keys")
    print(f"round {rnd}: passed {reported_passed}/{total}  failures_listed={len(fails)}{flag}")

print(f"\nrounds found: {len(paths)}/8")
print(f"UNION of failing tests across all rounds: {len(union)}\n")
for tid, occ in sorted(union.items(), key=lambda kv: -len(kv[1])):
    rounds = ",".join(str(r) for r, _, _ in occ)
    print(f"  [{len(occ)}/8 rounds: {rounds}] {tid}")

print("\n--- first error message per failing test (truncated 400 chars) ---")
for tid in sorted(union):
    print(f"\n### {tid}\n{first_err.get(tid, '')[:400]}")
