#!/usr/bin/env python3
"""Summarize the 8 per-round results.$i.json files from a sweep.

The runner's schema is: top-level {"total":N,"passed":N,...,"tests":[...]} where each
test entry uses the keys "name"/"nodeid", "status" (NOT pytest's "outcome") and
"error_message" (NOT "message"). Keying on the wrong names silently yields a fake
clean report, so this script cross-checks the union size against total-passed and
shouts if they disagree.

Usage:  python3 summarize_sweep.py            # all rounds, union of failures
        python3 summarize_sweep.py -v <name>  # full detail for one test
"""
import glob
import json
import os
import sys

IMPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "implementation")


def load():
    rounds = {}
    for path in sorted(glob.glob(os.path.join(IMPL, "results.*.json"))):
        idx = os.path.basename(path).split(".")[1]
        try:
            with open(path) as fh:
                rounds[idx] = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            rounds[idx] = {"_load_error": str(exc)}
    return rounds


def name_of(t):
    return t.get("nodeid") or t.get("name") or t.get("test") or "<unnamed>"


def status_of(t):
    return (t.get("status") or t.get("outcome") or "").lower()


def detail_of(t):
    for k in ("error_message", "message", "longrepr", "traceback", "detail"):
        if t.get(k):
            return str(t[k])
    return ""


def main():
    rounds = load()
    if not rounds:
        print("NO results.*.json FOUND — the sweep never produced output.")
        print("Do NOT interpret this as a pass. Check that sweep.sh ran with the cd")
        print("into implementation/ and that SWEEP_DONE exists.")
        return 2

    verbose_target = None
    if len(sys.argv) > 2 and sys.argv[1] == "-v":
        verbose_target = sys.argv[2]

    union = {}
    print(f"{'round':>6} {'total':>6} {'passed':>7} {'failed(listed)':>15}  verdict")
    all_clean = True
    for idx in sorted(rounds, key=lambda x: int(x) if x.isdigit() else 99):
        r = rounds[idx]
        if "_load_error" in r:
            print(f"{idx:>6} {'?':>6} {'?':>7} {'?':>15}  LOAD ERROR: {r['_load_error']}")
            all_clean = False
            continue
        total = r.get("total", 0)
        passed = r.get("passed", 0)
        tests = r.get("tests", []) or []
        bad = [t for t in tests if status_of(t) not in ("passed", "pass", "ok", "")]
        for t in bad:
            union.setdefault(name_of(t), {})[idx] = t
        clean = total > 0 and passed == total
        all_clean = all_clean and clean
        flag = "CLEAN" if clean else "FAIL"
        if len(bad) != (total - passed):
            flag += f"  !! listed-failures({len(bad)}) != total-passed({total - passed}) — key-name mismatch, inspect raw json"
        print(f"{idx:>6} {total:>6} {passed:>7} {len(bad):>15}  {flag}")

    print()
    if all_clean and not union:
        print("ALL 8 ROUNDS CLEAN — passed == total everywhere.")
        return 0

    print(f"UNION OF FAILING TESTS ACROSS ALL ROUNDS: {len(union)}")
    print("(a test failing in any single round counts — that is the flakiness signal)")
    print()
    for name in sorted(union):
        where = sorted(union[name], key=lambda x: int(x) if x.isdigit() else 99)
        tag = "FLAKY" if len(where) < len(rounds) else "always"
        print(f"  [{tag:>6}] rounds {','.join(where)}  {name}")
        if verbose_target and verbose_target in name:
            print("  " + "-" * 70)
            print(detail_of(union[name][where[0]]))
            print("  " + "-" * 70)
    if not verbose_target:
        print()
        print("First failure detail per distinct error signature:")
        seen = set()
        for name in sorted(union):
            t = list(union[name].values())[0]
            d = detail_of(t)
            sig = d.strip().splitlines()[-1][:120] if d.strip() else "<no detail>"
            if sig in seen:
                continue
            seen.add(sig)
            print(f"\n=== {name}\n{d[:2000]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
