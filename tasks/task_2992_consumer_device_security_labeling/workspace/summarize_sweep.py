#!/usr/bin/env python3
"""Summarize the 8-round sweep for task_2992_consumer_device_security_labeling.

Usage:
    python3 /home/ubuntu/github/CodingPRD/tasks/task_2992_consumer_device_security_labeling/workspace/summarize_sweep.py
    python3 .../summarize_sweep.py --detail        # also print first error line per failing test
    python3 .../summarize_sweep.py --test NAME     # print full error_message for one test, per round

Schema note (verified against prd_bench_local_runner/results.py): the runner writes
top-level {total, passed, failed, errors, skipped, duration_seconds, tests[]} and each
element of tests[] is {name, file, status, duration_seconds, error_message}. The key is
"status" (values "passed"/"failed"/"error"/"skipped") -- NOT pytest's "outcome". A
summarizer keyed on "outcome" silently reports zero failures next to passed < total.
This script cross-checks the failing-set size against (total - passed) and shouts if
they disagree, so a key-name mistake cannot masquerade as a clean round.
"""

import argparse
import json
import sys
from pathlib import Path

IMPL = Path("/home/ubuntu/github/CodingPRD/tasks/task_2992_consumer_device_security_labeling/workspace/implementation")
BAD = {"failed", "error"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--test", default=None)
    args = ap.parse_args()

    rounds = {}
    for i in range(1, 9):
        p = IMPL / f"results.{i}.json"
        if not p.exists():
            print(f"round {i}: MISSING {p.name} -- sweep not finished or round died at t=0")
            continue
        try:
            rounds[i] = json.loads(p.read_text())
        except Exception as exc:  # truncated / mid-write
            print(f"round {i}: UNREADABLE ({exc})")

    if not rounds:
        print("\nNO RESULTS AT ALL. Do not diagnose the implementation. Check, in order:")
        print("  1. is the sweep still running?  ls .../workspace/SWEEP_DONE")
        print("  2. did --start-command keep its `cd <impl dir> &&` prefix?")
        print("  3. tail the per-round server logs, not sweep.log (8 rounds share one fd).")
        return 2

    union = {}
    clean = True
    for i, r in sorted(rounds.items()):
        total, passed = r.get("total", 0), r.get("passed", 0)
        fails = [t for t in r.get("tests", []) if t.get("status") in BAD]
        expected = total - passed - r.get("skipped", 0)
        flag = ""
        if len(fails) != expected:
            flag = f"  <<< KEY-NAME MISMATCH: {len(fails)} collected vs {expected} implied"
        print(f"round {i}: {passed}/{total} passed  "
              f"failed={r.get('failed')} errors={r.get('errors')} skipped={r.get('skipped')}  "
              f"{r.get('duration_seconds', 0):.0f}s{flag}")
        if passed != total:
            clean = False
        for t in fails:
            union.setdefault(t["name"], {})[i] = t.get("error_message") or ""

    if len(rounds) < 8:
        clean = False
        print(f"\nONLY {len(rounds)}/8 ROUNDS PRESENT -- not a clean sweep regardless of pass counts.")

    print(f"\nunion of failing tests across all rounds: {len(union)}")
    for name in sorted(union):
        where = sorted(union[name])
        tag = "FLAKY" if len(where) < len(rounds) else "always"
        print(f"  [{tag} {len(where)}/{len(rounds)}] {name}")
        if args.detail:
            first = union[name][where[0]].strip().split("\n")
            print(f"        {first[-1][:200] if first else ''}")

    if args.test:
        print(f"\n=== full error_message for {args.test} ===")
        for i in sorted(rounds):
            for t in rounds[i].get("tests", []):
                if args.test in t["name"] and t.get("status") in BAD:
                    print(f"\n--- round {i} ---\n{t.get('error_message')}")

    print("\nVERDICT:", "CLEAN 8/8" if clean and not union else "NOT CLEAN")
    return 0 if (clean and not union) else 1


if __name__ == "__main__":
    sys.exit(main())
