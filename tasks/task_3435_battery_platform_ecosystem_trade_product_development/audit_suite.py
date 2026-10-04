"""Completion + citation audit for the generated test suite.

(a) loads both design yamls, collects every non-stub instance's expected tag
(b) AST-walks test_suite/*.py, extracts every test function's Design tag
(c) diffs both directions and checks per-instance counts (difficulty >= 2,
    corner >= 1)
(d) verifies every >=6-word quoted fragment in each test docstring appears
    verbatim (whitespace-normalized) in PRD.md
"""
import ast
import glob
import re
import sys

import yaml

TASK = "/home/ubuntu/github/CodingPRD/tasks/task_3435_battery_platform_ecosystem_trade_product_development"

# --- (a) expected tags from the design indices ---
expected = {}  # tag -> ("Difficulty"|"Corner", min_tests)
with open(f"{TASK}/SCAFFOLD_DIFFICULTY_DESIGN.yaml") as f:
    diff = yaml.safe_load(f)["scaffold_difficulty_design"]
for rule in diff:
    for inst in rule["instances"]:
        tag = f"Difficulty/{rule['rule_id']}/{inst['name']}"
        expected[tag] = ("Difficulty", 2)

stub_tags = set()
with open(f"{TASK}/SCAFFOLD_CORNER_DESIGN.yaml") as f:
    corner = yaml.safe_load(f)["scaffold_corner_design"]
for sec in corner:
    for inst in sec["instances"]:
        tag = f"Corner/{sec['section']}/{inst['name']}"
        if "excluded_because" in inst:
            stub_tags.add(tag)
        else:
            expected[tag] = ("Corner", 1)

# --- (b) emitted tags from test_suite ---
emitted = {}  # tag -> list of (file, func)
docstrings = []  # (file, func, docstring)
for path in sorted(glob.glob(f"{TASK}/test_suite/test_*.py")):
    tree = ast.parse(open(path).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            doc = ast.get_docstring(node) or ""
            docstrings.append((path.split("/")[-1], node.name, doc))
            tags = re.findall(r"^Design:\s*(\S+)\s*$", doc, re.M)
            for t in tags:
                emitted.setdefault(t, []).append((path.split("/")[-1], node.name))
            if len(tags) != 1:
                print(f"TAG-COUNT FAIL {path.split('/')[-1]}::{node.name}: {len(tags)} tags")

# --- (c) diffs both ways ---
print("=== EXPECTED (non-stub) ===")
print(f"Difficulty instances: {sum(1 for v in expected.values() if v[0]=='Difficulty')}")
print(f"Corner instances:     {sum(1 for v in expected.values() if v[0]=='Corner')}")
print(f"Corner stubs (not translated): {len(stub_tags)}")
for t in sorted(stub_tags):
    print(f"  stub: {t}")

missing = sorted(set(expected) - set(emitted))
extra = sorted(set(emitted) - set(expected))
print("\n=== MISSING (expected but no test) ===")
for t in missing:
    print(f"  {t}")
print("=== EXTRA (emitted but not in index) ===")
for t in extra:
    print(f"  {t}")

print("\n=== PER-INSTANCE COUNTS ===")
shortfalls = []
for tag, (queue, need) in sorted(expected.items()):
    got = len(emitted.get(tag, []))
    flag = "OK " if got >= need else "SHORT"
    if got < need:
        shortfalls.append(tag)
    print(f"  [{flag}] {got}>= {need}  {tag}")
n_tests = sum(len(v) for v in emitted.values())
print(f"\nTotal emitted tests with exactly one tag: {n_tests}")
print(f"Missing: {len(missing)}  Extra: {len(extra)}  Shortfalls: {len(shortfalls)}")

# --- (d) verbatim PRD citation check ---
prd = open(f"{TASK}/workspace/PRD.md").read()
norm_prd = re.sub(r"\s+", " ", prd)

citation_failures = []
for fname, func, doc in docstrings:
    if not doc:
        citation_failures.append((fname, func, "NO DOCSTRING"))
        continue
    for quoted in re.findall(r'"([^"]+)"', doc):
        if quoted.startswith("Design:"):
            continue
        for frag in re.split(r"\.\.\.|…", quoted):
            frag = re.sub(r"\s+", " ", frag).strip().strip('"')
            if len(frag.split()) >= 6:
                if frag not in norm_prd:
                    citation_failures.append((fname, func, frag[:90]))

print("\n=== CITATION VERBATIM FAILURES ===")
for fname, func, frag in citation_failures:
    print(f"  {fname}::{func}: {frag!r}")
print(f"citation failures: {len(citation_failures)}")

sys.exit(1 if (missing or extra or shortfalls or citation_failures) else 0)
