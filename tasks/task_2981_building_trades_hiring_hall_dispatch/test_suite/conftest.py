"""
Shared pytest fixtures for the Building Trades Hiring Hall Dispatch suite.

The harness owns the server lifecycle and restarts it before every individual
test, so each test begins against an empty hall: no locals, no members, no
lists, and the logical clock reading its untouched default of §2.5.
"""

import pytest

from test_helpers import HiringHallApiClient


@pytest.fixture
def api() -> HiringHallApiClient:
    """A client bound to the API under test."""
    return HiringHallApiClient()
