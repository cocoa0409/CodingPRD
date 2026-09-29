"""Shared pytest fixtures for the dispensing API suite.

The harness restarts the server before every test, so the database is empty at
the start of each one and the logical clock reads its startup instant. Every
fixture therefore builds whatever it needs from scratch through the API.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import DmeApiClient, build_practice  # noqa: E402


@pytest.fixture
def api() -> DmeApiClient:
    """A client pointed at the server under test."""
    return DmeApiClient()


@pytest.fixture
def practice(api):
    """One accredited clinic with a roster, an attested supplier, a
    prefabricated catalog item and a shelf holding ten units."""
    return build_practice(api)
