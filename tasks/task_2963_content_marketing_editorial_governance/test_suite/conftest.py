"""
Shared pytest wiring for the editorial governance suite.

The service is restarted before every individual test, so each test opens
against an empty database; the fixtures below hand out a fresh client and a
fresh setup builder for every case.
"""

import os
import sys

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.fixtures import api, flow  # noqa: E402,F401

__all__ = ["api", "flow"]
