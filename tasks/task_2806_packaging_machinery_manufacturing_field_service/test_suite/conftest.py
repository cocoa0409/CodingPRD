"""Pytest configuration for the Packaging Machinery OEM API suite.

The shared infrastructure lives in the sibling `test_helpers` package, so the
task root is put on `sys.path` before any test module imports it.

Each test runs against a freshly started server with an empty database, so
there is no shared session state and no cleanup fixture: every test builds the
preconditions it needs from the service's own endpoints.
"""

import os
import sys

import pytest

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

from test_helpers import api_client  # noqa: E402


@pytest.fixture
def client():
    """The API client bound to the service under test."""
    return api_client
