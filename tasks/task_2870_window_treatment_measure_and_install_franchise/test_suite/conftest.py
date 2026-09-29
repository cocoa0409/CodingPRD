"""Shared pytest wiring for the franchise API compliance suite.

The API server is relaunched before every individual test, so each test begins
against an empty database and must charter whatever it needs.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  registers error -> HTTP map
from test_helpers.api_client import BlindsApiClient  # noqa: E402
from test_helpers.fixtures import *  # noqa: E402,F401,F403


@pytest.fixture
def api() -> BlindsApiClient:
    """A client bound to the API under test."""
    return BlindsApiClient()
