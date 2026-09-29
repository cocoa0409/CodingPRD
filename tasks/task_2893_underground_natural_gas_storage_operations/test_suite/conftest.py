"""Shared pytest configuration for the Underground Gas Storage Operations suite.

The harness restarts the API server before every individual test, so every test
below starts against an empty database with the logical clock reading exactly
`2026-08-01T00:00:00Z`.
"""

import os
import sys

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

# Registering the error catalogue wires the error_id -> HTTP status cross-check
# into every validate_error call in the suite.
from test_helpers import api_errors  # noqa: E402,F401
from test_helpers.fixtures import (  # noqa: E402,F401
    api,
    bare_field,
    bound_world,
    mini_world,
    std_world,
)
