"""Shared pytest configuration for the manufacturing compliance suite.

The service is restarted before every individual test, so each test opens
against an empty store and builds its own preconditions through the PRD's own
endpoints. The only shared state here is the API client itself.
"""

import os
import sys

import pytest

# The helper package lives beside this directory at the task root; make it
# importable regardless of the rootdir pytest happens to be invoked from.
_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers import MfgApiClient  # noqa: E402


@pytest.fixture
def api():
    """A client pointed at the service under test."""
    return MfgApiClient()
