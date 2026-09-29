#!/usr/bin/env python3
"""Summarize the 8-round sweep for task_2985 from per-round results.$i.json.

Diagnose ONLY from these files, never from sweep.log (8 rounds share one fd).

Runner schema note: each entry in results["tests"] uses the keys `status` and
`error_message` (NOT pytest's `outcome`/`message`). Keying on the wrong name
silently reports zero failures next to passed<total, so this script cross-checks
the union size against (total - passed) and shouts if they disagree.
"""
import glob
import json
import os
import sys
from collections import defaultdict

IMPL = "/home/ubuntu/github/CodingPRD/tasks/task_2985_executive_protection_travel_risk_management/workspace/implementation"

files = sorted(glob.glob(os.path.join(IMPL, "results.*.json")))
if not files:
    print("NO results.*.json FILES FOUND — the sweep did not run (check the "
          "--start-command has its `cd`, and that sweep.sh was launched under setsid).")
    sys.exit(1)

union = defaultdict(list)   # test name -> [(round, status, error_message)]
rounds_ok = []
print(f"found {len(files)} round file(s)\n")

for path in files:
    rnd = os.path.basename(path).split(".")[1]
    try:
        with open(path) as fh:
            data = json.load(fh)
    except Exception as exc:                      # noqa: BLE001
        print(f"round {rnd}: UNREADABLE ({exc})")
        rounds_ok.append(False)
        continue

    total = data.get("total")
    passed = data.get("passed")
    tests = data.get("tests") or []
    bad = [t for t in tests if t.get("status") not in ("passed", "PASSED", "pass")]
    for t in bad:
        union[t.get("name") or t.get("nodeid") or "<unnamed>"].append(
            (rnd, t.get("status"), (t.get("error_message") or "")[:400])
        )

    clean = (passed == total) and total
    rounds_ok.append(bool(clean))
    flag = "CLEAN" if clean else "FAIL"
    print(f"round {rnd}: {flag}  passed={passed} total={total}  "
          f"non-passing entries={len(bad)}  top_keys={sorted(data.keys())}")
    if total is not None and passed is not None and (total - passed) != len(bad):
        print(f"  !! KEY-NAME WARNING: total-passed={total - passed} but only "
              f"{len(bad)} non-passing entries found — check the results schema "
              f"(status/error_message vs outcome/message).")

print(f"\n=== UNION OF FAILING TESTS ACROSS ALL ROUNDS: {len(union)} ===")
for name, occ in sorted(union.items()):
    rs = ",".join(o[0] for o in occ)
    print(f"\n--- {name}\n    failed in rounds: {rs} ({len(occ)}/{len(files)})")
    print(f"    {occ[0][2]}")

print(f"\nALL 8 ROUNDS CLEAN: {len(files) == 8 and all(rounds_ok)}")
