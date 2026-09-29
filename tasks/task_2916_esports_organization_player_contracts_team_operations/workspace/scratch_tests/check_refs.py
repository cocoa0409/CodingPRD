"""Audit: every api_client./fixtures./factories./assertions./ApiErrorId. reference resolves."""
import ast
import sys
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/github/CodingPRD/tasks/task_2916_esports_organization_player_contracts_team_operations")

import test_helpers as th
from test_helpers import api_client, assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId

MODULES = {
    "api_client": api_client,
    "fixtures": fixtures,
    "factories": factories,
    "assertions": assertions,
    "ApiErrorId": ApiErrorId,
}

missing = []
for path in sorted(sys.argv[1:]):
    tree = ast.parse(Path(path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            base = node.value.id
            if base in MODULES and not hasattr(MODULES[base], node.attr):
                missing.append(f"{path}:{node.lineno} {base}.{node.attr}")
    # imported names from test_helpers
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "test_helpers":
            for alias in node.names:
                if not hasattr(th, alias.name):
                    missing.append(f"{path}: import {alias.name}")
print("MISSING:", missing or "none")
