"""Audit: every PRD: "..." quote is verbatim, every test carries exactly one Design tag."""
import ast
import re
import sys
from pathlib import Path

ROOT = Path("/home/ubuntu/github/CodingPRD/tasks/task_2916_esports_organization_player_contracts_team_operations")
PRD = ROOT / "workspace" / "PRD.md"
CORNER = ROOT / "SCAFFOLD_CORNER_DESIGN.yaml"
DIFF = ROOT / "SCAFFOLD_DIFFICULTY_DESIGN.yaml"


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


prd = norm(PRD.read_text())
corner_names = set(re.findall(r"^\s*- name: (\S+)", CORNER.read_text(), re.M))
diff_names = set(re.findall(r"^\s*- name: (\S+)", DIFF.read_text(), re.M))

bad = 0
for path in sorted(sys.argv[1:]):
    tree = ast.parse(Path(path).read_text())
    tests = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    for fn in tests:
        doc = ast.get_docstring(fn, clean=False) or ""
        tags = re.findall(r"Design: (Difficulty|Corner)/([^/\n]+)/(\S+)", doc)
        if len(tags) != 1:
            print(f"TAGCOUNT {path}::{fn.name} -> {len(tags)}")
            bad += 1
        for queue, _section, name in tags:
            pool = diff_names if queue == "Difficulty" else corner_names
            if name not in pool:
                print(f"BADNAME {path}::{fn.name} -> {name}")
                bad += 1
        last = [ln for ln in doc.strip().splitlines() if ln.strip()][-1].strip()
        if not last.startswith("Design: "):
            print(f"TRAILING {path}::{fn.name} -> {last[:60]}")
            bad += 1
        for quote in re.findall(r'PRD: "(.*?)"\s*(?:\n|$)', doc, re.S):
            if norm(quote) not in prd:
                print(f"QUOTE {path}::{fn.name} -> {norm(quote)[:110]}")
                bad += 1
    print(f"{path}: {len(tests)} tests")
print("PROBLEMS:", bad)
