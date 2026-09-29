"""Shared fixtures for the vendor credentialing and OR access suite.

The server under test is restarted before every test, so each test starts from an
empty store and builds everything it needs through the declared endpoints. The
logical clock therefore reads its startup default of ``2026-08-01T00:00:00Z`` at
the top of every test unless the test moves it.
"""

from __future__ import annotations

import pytest

from test_helpers import VendorAccessApiClient


@pytest.fixture
def api() -> VendorAccessApiClient:
    """A client aimed at the server under test."""
    return VendorAccessApiClient()
