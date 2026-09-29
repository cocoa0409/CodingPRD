#!/usr/bin/env python3
"""Summarize the 8-round sweep for task_2996.

Usage:
    python3 workspace/summarize_sweep.py            # summary + union of failing tests
    python3 workspace/summarize_sweep.py -v         # also print each failure's error_message

Schema notes (getting these wrong has produced fake "clean" rounds before):
  * The runner writes per-test records under the top-level key "tests".
  * Each record's outcome lives in "status" -- NOT pytest's "outcome".
  * The failure text lives in "error_message" -- NOT "message" / "longrepr".
  * Round totals are "passed" and "total".
A summarizer keyed on the wrong names silently reports zero failures while
`passed < total`, so this script cross-checks the union size against
(total - passed) and shouts if they disagree.
"""
import glob
import json
import os
import sys

IMPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "implementation")
VERBOSE = "-v" in sys.argv

paths = sorted(glob.glob(os.path.join(IMPL, "results.*.json")))
if not paths:
    print("NO RESULTS FILES. The sweep never produced output -- do not diagnose the "
          "implementation from this. Check that --start-command contains the `cd` into "
          "the implementation dir, and that the sweep was launched under setsid.")
    sys.exit(2)

union = {}          # test id -> {round: error_message}
rounds = []

for p in paths:
    try:
        with open(p) as fh:
            data = json.load(fh)
    except Exception as exc:                      # truncated / mid-write file
        print(f"{os.path.basename(p)}: UNREADABLE ({exc})")
        continue

    rnd = os.path.basename(p).split(".")[1]
    passed = data.get("passed")
    total = data.get("total")
    tests = data.get("tests") or []
    fails = [t for t in tests if t.get("status") not in ("passed", "PASSED", "pass")]
    rounds.append((rnd, passed, total, len(fails)))

    for t in fails:
        tid = t.get("test_id") or t.get("nodeid") or t.get("name") or "<unnamed>"
        union.setdefault(tid, {})[rnd] = (t.get("error_message") or "").strip()

    # Cross-check: the per-test scan must account for every non-pass.
    if isinstance(passed, int) and isinstance(total, int):
        if (total - passed) != len(fails):
            print(f"  !! {os.path.basename(p)}: total-passed={total - passed} but only "
                  f"{len(fails)} non-passing records found -- schema key mismatch, "
                  f"do NOT trust this round")

print(f"=== {len(paths)} result file(s) ===")
for rnd, passed, total, nf in rounds:
    flag = "CLEAN" if (passed == total and nf == 0) else "FAIL"
    print(f"  round {rnd}: passed={passed} total={total} failing={nf}  [{flag}]")

print(f"\n=== union of failing tests across all rounds: {len(union)} ===")
for tid, per_round in sorted(union.items()):
    print(f"\n  {tid}")
    print(f"    failed in rounds: {','.join(sorted(per_round))} "
          f"({len(per_round)}/{len(rounds)} rounds{'  <-- FLAKY' if len(per_round) < len(rounds) else ''})")
    if VERBOSE:
        msg = next(iter(per_round.values()))
        for line in msg.splitlines()[-25:]:
            print(f"      {line}")

all_clean = bool(rounds) and all(p == t and nf == 0 for _, p, t, nf in rounds)
print("\nVERDICT:", "ALL ROUNDS CLEAN -- Step 7 may exit" if all_clean and len(paths) == 8
      else f"NOT CLEAN ({len(union)} tests in the failing union across {len(paths)} round file(s))")
