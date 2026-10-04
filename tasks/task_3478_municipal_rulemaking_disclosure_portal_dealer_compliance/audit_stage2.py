"""Stage-2 self-audit: AST-walk test_suite/*.py, extract every `Design:` tag,
resolve each against the two design yamls, verify coverage rules, and check
that every >=8-word quoted span in each test docstring survives a whitespace-
normalized literal grep of workspace/PRD.md.
"""
import ast
import re
import sys
from pathlib import Path

import yaml

TASK = Path("/home/ubuntu/github/CodingPRD/tasks/task_3478_municipal_rulemaking_disclosure_portal_dealer_compliance")
SUITE = TASK / "test_suite"
PRD = (TASK / "workspace" / "PRD.md").read_text()


def norm(text: str) -> str:
    return " ".join(text.split())


PRD_NORM = norm(PRD)

# --- Load design indices -------------------------------------------------------
diff = yaml.safe_load((TASK / "SCAFFOLD_DIFFICULTY_DESIGN.yaml").read_text())["scaffold_difficulty_design"]
corner = yaml.safe_load((TASK / "SCAFFOLD_CORNER_DESIGN.yaml").read_text())["scaffold_corner_design"]

difficulty_instances = {}   # tag -> name
for rule in diff:
    for inst in rule["instances"]:
        difficulty_instances[f"Difficulty/{rule['rule_id']}/{inst['name']}"] = inst["name"]

corner_active = {}          # tag -> name
corner_stubbed = set()
for section in corner:
    for inst in section["instances"]:
        tag = f"Corner/{section['section']}/{inst['name']}"
        if "excluded_because" in inst:
            corner_stubbed.add(tag)
        else:
            corner_active[tag] = inst["name"]

# --- AST-walk the suite --------------------------------------------------------
tag_to_tests = {}           # tag -> [test names]
problems = []
test_count = 0
citation_failures = []

for path in sorted(SUITE.glob("test_*.py")):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            test_count += 1
            doc = ast.get_docstring(node)
            if doc is None:
                problems.append(f"{path.name}:{node.name}: no docstring")
                continue
            tags = [ln.split("Design:", 1)[1].strip()
                    for ln in doc.splitlines() if ln.strip().startswith("Design:")]
            if len(tags) != 1:
                problems.append(f"{path.name}:{node.name}: {len(tags)} Design tags")
                continue
            tag = tags[0]
            if tag not in difficulty_instances and tag not in corner_active:
                if tag in corner_stubbed:
                    problems.append(f"{path.name}:{node.name}: tag points at STUBBED instance {tag}")
                else:
                    problems.append(f"{path.name}:{node.name}: tag resolves to nothing: {tag}")
                continue
            tag_to_tests.setdefault(tag, []).append(f"{path.name}::{node.name}")

            # Citation verbatim check: every quoted span with >=8 words must
            # appear (whitespace-normalized) in PRD.md.
            body = doc.split("Design:")[0]
            for span in re.findall(r'"([^"]+)"', body):
                if len(span.split()) >= 8 and norm(span) not in PRD_NORM:
                    citation_failures.append(f"{path.name}:{node.name}: quote not in PRD: {span[:90]}...")

# --- Coverage rules --------------------------------------------------------------
diff_missing = [t for t, name in difficulty_instances.items()
                if len(tag_to_tests.get(t, [])) < 2]
corner_missing = [t for t, name in corner_active.items() if t not in tag_to_tests]
diff_under = [t for t in tag_to_tests if t in difficulty_instances and len(tag_to_tests[t]) < 2]

print(f"tests collected by AST: {test_count}")
print(f"difficulty instances: {len(difficulty_instances)}; covered >=2: "
      f"{sum(1 for t in difficulty_instances if len(tag_to_tests.get(t, [])) >= 2)}; "
      f"missing/under-covered: {len(diff_missing)}")
print(f"corner active instances: {len(corner_active)}; covered >=1: "
      f"{sum(1 for t in corner_active if t in tag_to_tests)}; missing: {len(corner_missing)}")
print(f"corner stubbed (excluded_because, must stay untagged): {len(corner_stubbed)}; "
      f"tagged anyway: {sum(1 for t in corner_stubbed if t in tag_to_tests)}")
print(f"difficulty tags used: {sum(len(v) for k, v in tag_to_tests.items() if k.startswith('Difficulty/'))}")
print(f"corner tags used: {sum(len(v) for k, v in tag_to_tests.items() if k.startswith('Corner/'))}")

if diff_missing:
    print("\nMISSING/UNDER DIFFICULTY:")
    for t in diff_missing:
        print(f"  {t} -> {len(tag_to_tests.get(t, []))} test(s)")
if corner_missing:
    print("\nMISSING CORNER:")
    for t in corner_missing:
        print(f"  {t}")
if problems:
    print("\nTAG PROBLEMS:")
    for p in problems:
        print(f"  {p}")
if citation_failures:
    print("\nCITATION VERBATIM FAILURES:")
    for c in citation_failures:
        print(f"  {c}")

ok = not (diff_missing or corner_missing or problems or citation_failures)
print(f"\nAUDIT: {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
