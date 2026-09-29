"""Pytest bridge to the shared test infrastructure.

The harness restarts the API server before every individual test, so every
fixture below is stateless: it hands back a client or a header set and never
caches data across tests.
"""

import os
import sys
from typing import Dict

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    api_client,
    make_administrator_headers,
    make_officer_headers,
    make_regulator_headers,
    make_sponsor_headers,
)
from test_helpers.test_users import (  # noqa: E402
    OFFICER_USER_ID,
    OFFICER_USER_ID_ALT,
    REGULATOR_USER_ID,
    SPONSOR_USER_ID,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The typed HTTP client for the parity API."""
    return api_client


@pytest.fixture
def sponsor_headers() -> Dict[str, str]:
    """Identity headers for the plan sponsor (`user-sponsor-01`)."""
    return make_sponsor_headers(SPONSOR_USER_ID)


@pytest.fixture
def officer_headers() -> Dict[str, str]:
    """Identity headers for the first compliance officer (`user-officer-01`)."""
    return make_officer_headers(OFFICER_USER_ID)


@pytest.fixture
def officer_alt_headers() -> Dict[str, str]:
    """Identity headers for the independent second officer (`user-officer-02`)."""
    return make_officer_headers(OFFICER_USER_ID_ALT)


@pytest.fixture
def regulator_headers() -> Dict[str, str]:
    """Identity headers for regulatory staff (`user-regulator-01`)."""
    return make_regulator_headers(REGULATOR_USER_ID)


@pytest.fixture
def administrator_headers_for():
    """Build Administrator identity headers for a given administrator id.

    The Administrator role is entity-backed, so its `X-User-ID` is the id of the
    Administrator row created during the test's own setup.
    """
    return make_administrator_headers
