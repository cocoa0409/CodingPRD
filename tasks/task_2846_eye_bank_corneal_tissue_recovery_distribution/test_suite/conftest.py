"""
Shared pytest fixtures for the eye bank API compliance suite.

The harness relaunches the server before every individual test, so each test starts
against an empty database and builds all of its own preconditions through the public
API. Nothing here is shared across tests.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import EyeBankApiClient, fixtures  # noqa: E402
from test_helpers.constants import T_NOW  # noqa: E402


@pytest.fixture
def api():
    """A client bound to the server under test."""
    return EyeBankApiClient()


@pytest.fixture
def pinned_api(api):
    """A client whose logical clock has been moved to the suite's reference instant."""
    fixtures.set_clock(api, T_NOW)
    return api
