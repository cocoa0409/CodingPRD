#!/usr/bin/env python3
"""Summarize the 8 per-round results.$i.json files from sweep.sh.

Prints per-round passed/total and the UNION of failing test ids across rounds.

Note: the runner's per-test records key the verdict as "status" (not "outcome").
This script therefore cross-checks the union size against (total - passed) per
round and shouts if they disagree, so a key-name change can never silently
report "zero failures" beside passed < total.
"""
import glob
import json
import os
import sys

IMPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "implementation")

VERDICT_KEYS = ("status", "outcome", "result")
PASSY = {"passed", "pass", "ok", "success"}


def test_records(doc):
    for key in ("tests", "results", "test_results", "cases"):
        v = doc.get(key)
        if isinstance(v, list):
            return v
    return []


def name_of(rec, idx):
    for key in ("nodeid", "test_id", "id", "name", "test"):
        v = rec.get(key)
        if isinstance(v, str) and v:
            return v
    return "<record #%d>" % idx


def verdict_of(rec):
    for key in VERDICT_KEYS:
        v = rec.get(key)
        if isinstance(v, str):
            return v.lower()
    return None


def main():
    paths = sorted(glob.glob(os.path.join(IMPL, "results.*.json")))
    if not paths:
        print("NO RESULTS FILES in %s -- the sweep never produced output." % IMPL)
        return 2

    union_failing = {}
    all_clean = True
    print("rounds found: %d" % len(paths))
    for p in paths:
        try:
            with open(p) as fh:
                doc = json.load(fh)
        except Exception as exc:  # truncated / mid-write file
            all_clean = False
            print("%-18s UNREADABLE: %s" % (os.path.basename(p), exc))
            continue

        total = doc.get("total")
        passed = doc.get("passed")
        recs = test_records(doc)
        failing = []
        for i, rec in enumerate(recs):
            v = verdict_of(rec)
            if v is None or v not in PASSY:
                failing.append((name_of(rec, i), v, rec))

        if total is None:
            total = len(recs)
        if passed is None:
            passed = total - len(failing)

        if total == 0:
            # A collection error (e.g. an ImportError in conftest) yields
            # total 0 / passed 0, which satisfies passed == total and would
            # otherwise be reported as a clean round. It is a false green:
            # no test ever ran.
            all_clean = False
            print(
                "%-18s COLLECTED 0 TESTS -- collection error, not a clean round "
                "(errors=%s)" % (os.path.basename(p), doc.get("errors"))
            )
            continue
        if passed != total:
            all_clean = False
        expected_fail = total - passed
        flag = ""
        if expected_fail != len(failing):
            flag = "  <== KEY MISMATCH: %d failures expected, %d found by verdict key" % (
                expected_fail,
                len(failing),
            )
        print(
            "%-18s passed %s/%s  failures-enumerated %d%s"
            % (os.path.basename(p), passed, total, len(failing), flag)
        )
        for nm, v, rec in failing:
            union_failing.setdefault(nm, []).append((os.path.basename(p), v))

    print("\nUNION of failing tests across all rounds: %d" % len(union_failing))
    for nm in sorted(union_failing):
        rounds = union_failing[nm]
        print("  %s   (failed in %d round(s): %s)" % (nm, len(rounds), ", ".join(r for r, _ in rounds)))

    print("\nVERDICT: %s" % ("ALL ROUNDS CLEAN" if all_clean and not union_failing else "NOT CLEAN"))
    return 0 if (all_clean and not union_failing) else 1


if __name__ == "__main__":
    sys.exit(main())
