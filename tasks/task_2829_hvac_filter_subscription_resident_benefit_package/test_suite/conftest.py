"""
Shared pytest fixtures.

The harness restarts the API server against an empty database before every
individual test, so no fixture here does any cleanup — each test builds the
world it needs through the public endpoints and then throws it away.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers import test_users  # noqa: E402


@pytest.fixture
def api():
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def operator():
    """ProgramOperator identity headers."""
    return test_users.OPERATOR


@pytest.fixture
def adjuster_a():
    """The adjuster who performs claim intake."""
    return test_users.ADJUSTER_A


@pytest.fixture
def adjuster_b():
    """A second, distinct adjuster who may decide what adjuster_a triaged."""
    return test_users.ADJUSTER_B
