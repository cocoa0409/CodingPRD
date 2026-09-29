"""Shared pytest fixtures for the Athletics Academic Eligibility API suite."""

import os
import sys

import pytest

# The runner puts the parent of this directory on sys.path so that
# ``test_helpers`` imports cleanly; keep working when pytest is invoked from
# elsewhere as well.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from test_helpers import AthleticsApiClient  # noqa: E402
from test_helpers import api_errors  # noqa: E402,F401  (registers status map)


@pytest.fixture
def api():
    """A client for the API under test.

    The harness restarts the server before every test, so each test starts
    against an empty database and builds all of its own state.
    """
    return AthleticsApiClient()
