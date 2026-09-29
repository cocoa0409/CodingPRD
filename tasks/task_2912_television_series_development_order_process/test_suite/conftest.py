"""Shared pytest fixtures for the television series development API suite.

The runner owns the server lifecycle and relaunches it before every test, so each
test opens on an empty database with the logical clock at its startup default of
2026-08-01T00:00:00Z. Nothing here seeds data; the composite fixtures in
``test_helpers.fixtures`` build every precondition through the public endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402
from test_helpers import api_errors  # noqa: E402,F401  (registers the status map)


@pytest.fixture
def api():
    """A fresh client bound to the runner's API_BASE_URL."""
    return ApiClient()
