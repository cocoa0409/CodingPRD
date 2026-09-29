"""Shared pytest fixtures for the Master Patient Index compliance suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import MpiApiClient  # noqa: E402
from test_helpers.constants import DEFAULT_CLOCK_UTC  # noqa: E402
from test_helpers.fixtures import pin_clock  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    admin_headers,
    analyst_headers,
    officer_headers,
    steward_headers,
)


@pytest.fixture()
def client() -> MpiApiClient:
    """An HTTP client bound to the service under test."""
    return MpiApiClient()


@pytest.fixture()
def api(client: MpiApiClient) -> MpiApiClient:
    """A client whose logical clock has been pinned to the documented default."""
    pin_clock(client, DEFAULT_CLOCK_UTC)
    return client


@pytest.fixture()
def admin():
    return admin_headers()


@pytest.fixture()
def analyst():
    return analyst_headers()


@pytest.fixture()
def steward():
    return steward_headers()


@pytest.fixture()
def officer():
    return officer_headers()
