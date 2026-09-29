"""
Shared pytest configuration for the Reentry Employment Services API suite.

Every test in this suite runs against a live server over HTTP. Nothing is
mocked and nothing is patched: each test drives the API exactly as a client
would, and asserts only on what the API returns.

The harness restarts the server before every individual test, so each test
begins against an empty database. That means a test may never rely on state
another test created; it builds every precondition it needs through the public
API, using the builders in test_helpers.fixtures.
"""

import os
import sys

# The helper package sits alongside this directory, at the task root.
_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.fixtures import api, build, clock  # noqa: E402,F401

__all__ = ["api", "build", "clock"]
