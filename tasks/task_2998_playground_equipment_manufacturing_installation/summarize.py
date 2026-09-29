#!/usr/bin/env python3
"""Summarize the 8 sweep rounds for task_2998.

NOTE ON SCHEMA: the runner writes tests[].status / tests[].error_message
(NOT pytest's outcome/message). Keying on the wrong name yields a fake clean
round. This script cross-checks the failure union against total-passed and
shouts if they disagree.
"""
import json, glob, os, sys, collections

IMPL = "/home/ubuntu/github/CodingPRD/tasks/task_2998_playground_equipment_manufacturing_installation/workspace/implementation"

files = sorted(glob.glob(os.path.join(IMPL, "results.*.json")))
if not files:
    sys.exit("NO results.*.json FOUND -- the sweep did not run (or was reaped). Do not diagnose; re-run under setsid.")

union = collections.defaultdict(list)   # test name -> [round ids]
print(f"rounds found: {len(files)}")
for f in files:
    rid = os.path.basename(f).split(".")[1]
    try:
        d = json.load(open(f))
    except Exception as e:
        print(f"  round {rid}: UNPARSEABLE ({e})")
        continue
    tests = d.get("tests") or []
    total = d.get("total", len(tests))
    passed = d.get("passed", sum(1 for t in tests if t.get("status") == "passed"))
    bad = [t for t in tests if t.get("status") not in ("passed", "skipped")]
    for t in bad:
        union[t.get("name") or t.get("nodeid") or "<unnamed>"].append(rid)
    flag = "" if len(bad) == (total - passed) else "  <-- KEY MISMATCH: bad-count != total-passed, check schema keys!"
    print(f"  round {rid}: passed={passed}/{total} listed_failures={len(bad)}{flag}")

print(f"\nunion of failing tests: {len(union)}")
for name, rounds in sorted(union.items(), key=lambda kv: (-len(kv[1]), kv[0])):
    tag = "ALL" if len(rounds) == len(files) else ",".join(rounds)
    print(f"  [{len(rounds)}/{len(files)} {tag}] {name}")

if not union:
    print("\nCLEAN SWEEP: all rounds passed == total.")
