#!/usr/bin/env python3
"""Summarise the 8-round sweep for task_2987.

Reads results.1.json .. results.8.json and prints:
  - per-round passed/total (and whether the round file is missing/unparsable)
  - the UNION of tests failing in ANY round, with the round(s) each failed in
  - a cross-check that the union size reconciles with (total - passed)

The runner's schema is: top-level {"passed": int, "total": int,
"tests": [{"name"/"test_id", "status": "passed"|"failed"|"error"|"skipped",
"error_message": str|None}, ...]}.  It is `status`, NOT pytest's `outcome`,
and `error_message`, NOT `message` -- keying on the wrong name silently
reports zero failures next to passed < total.

Usage:
  python3 summarize.py            # summary only
  python3 summarize.py -v         # + first 40 lines of each failure's message
"""
import json
import os
import sys
from collections import defaultdict

IMPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "implementation")
VERBOSE = "-v" in sys.argv

failing = defaultdict(list)   # test name -> [round numbers]
messages = {}                 # test name -> first error_message seen
rounds_ok = []

for i in range(1, 9):
    path = os.path.join(IMPL, "results.%d.json" % i)
    if not os.path.exists(path):
        print("round %d: MISSING %s" % (i, path))
        continue
    try:
        with open(path) as fh:
            data = json.load(fh)
    except Exception as exc:                      # noqa: BLE001
        print("round %d: UNPARSABLE (%s)" % (i, exc))
        continue

    tests = data.get("tests") or []
    passed = data.get("passed")
    total = data.get("total")
    if passed is None:
        passed = sum(1 for t in tests if t.get("status") == "passed")
    if total is None:
        total = len(tests)

    bad = [t for t in tests if t.get("status") not in ("passed", "skipped")]
    skipped = [t for t in tests if t.get("status") == "skipped"]
    print("round %d: passed=%s total=%s  non-passing=%d  skipped=%d" % (
        i, passed, total, len(bad), len(skipped)))

    # Cross-check: the enumerated non-passing count should reconcile with
    # total - passed.  A mismatch means either a key-name assumption is wrong
    # or tests vanished from the list entirely (collection error).
    if total - passed != len(bad) - len(skipped) and total - passed != len(bad):
        print("    WARNING round %d: total-passed=%s but enumerated non-passing=%d"
              " -- schema/collection anomaly, inspect the raw json" % (
                  i, total - passed, len(bad)))

    for t in bad:
        name = t.get("test_id") or t.get("name") or t.get("nodeid") or "<unnamed>"
        failing[name].append(i)
        if name not in messages:
            messages[name] = (t.get("status"), t.get("error_message") or "")
    rounds_ok.append(i)

print("\nrounds read: %s" % (rounds_ok,))
print("UNION of tests failing in >=1 round: %d\n" % len(failing))

for name in sorted(failing, key=lambda n: (-len(failing[n]), n)):
    rr = failing[name]
    flaky = "" if len(rr) == 8 else "   <-- FLAKY (%d/8)" % len(rr)
    status, msg = messages[name]
    print("[%s] %s  rounds=%s%s" % (status, name, rr, flaky))
    if VERBOSE and msg:
        for line in msg.splitlines()[:40]:
            print("      | " + line)
        print()

if not failing and len(rounds_ok) == 8:
    print("ALL 8 ROUNDS CLEAN")
