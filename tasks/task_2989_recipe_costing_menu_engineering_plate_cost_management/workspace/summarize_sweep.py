#!/usr/bin/env python3
"""Summarize the 8-round sweep for task_2989.

Run:  python3 /home/ubuntu/github/CodingPRD/tasks/task_2989_recipe_costing_menu_engineering_plate_cost_management/workspace/summarize_sweep.py

Schema note (do NOT guess): the runner writes per-test entries under `tests`
with keys `status` and `error_message`. There is no pytest-style `outcome` /
`message` key. A summarizer keyed on the wrong name silently prints "0 failures"
next to passed < total, so this script cross-checks the union of named failures
against (total - passed) per round and shouts if they disagree.
"""
import glob
import json
import os
import sys
from collections import defaultdict

IMPL = "/home/ubuntu/github/CodingPRD/tasks/task_2989_recipe_costing_menu_engineering_plate_cost_management/workspace/implementation"

PASS_STATUSES = {"passed", "pass", "ok", "success"}


def main():
    files = sorted(glob.glob(os.path.join(IMPL, "results.*.json")))
    if not files:
        print("NO results.*.json FOUND -- the sweep did not run (or died at t=0).")
        return 1

    print(f"rounds with results files: {len(files)} / 8")
    union = defaultdict(set)   # test id -> set of rounds it failed in
    details = {}               # test id -> first seen error text
    all_clean = True

    for f in files:
        try:
            data = json.load(open(f))
        except Exception as e:  # truncated / half-written file
            print(f"{os.path.basename(f)}: UNREADABLE ({e})")
            all_clean = False
            continue

        rnd = os.path.basename(f).split(".")[1]
        total = data.get("total")
        passed = data.get("passed")
        tests = data.get("tests") or []
        named = []
        for t in tests:
            st = str(t.get("status", "")).lower()
            if st not in PASS_STATUSES:
                tid = t.get("test_id") or t.get("name") or t.get("nodeid") or "<unnamed>"
                named.append(tid)
                union[tid].add(rnd)
                details.setdefault(tid, (st, (t.get("error_message") or "")[:4000]))

        flag = ""
        if isinstance(total, int) and isinstance(passed, int):
            if passed != total:
                all_clean = False
            expected_failures = total - passed
            if expected_failures != len(named):
                flag = (f"  <<< MISMATCH: total-passed={expected_failures} but "
                        f"{len(named)} tests named as non-passing -- check the status key")
        else:
            all_clean = False
            flag = "  <<< missing total/passed keys"

        print(f"round {rnd}: passed={passed} total={total} "
              f"non-passing-named={len(named)} error={data.get('error') or ''}{flag}")

    if len(files) < 8:
        all_clean = False

    print()
    if not union and all_clean:
        print("ALL 8 ROUNDS CLEAN")
        return 0

    print(f"UNION of failing tests across rounds: {len(union)}")
    for tid in sorted(union, key=lambda k: (-len(union[k]), k)):
        st, msg = details.get(tid, ("", ""))
        print(f"\n=== {tid}  [failed in rounds: {','.join(sorted(union[tid]))}] status={st}")
        print(msg)
    return 1


if __name__ == "__main__":
    sys.exit(main())
