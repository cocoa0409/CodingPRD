"""Pytest wiring for the fixed-price-point retail conversion suite.

The harness restarts the API server before every test, so each test starts
against an empty database and builds its own world through the public API. The
base URL is injected into the environment by the runner.
"""

import pytest

from test_helpers import ApiClient
from test_helpers import fixtures


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def world(api: ApiClient):
    """Baseline state: the logical clock pinned at its startup instant."""
    return fixtures.seed_reference_data()


# ─── role header fixtures ─────────────────────────────────────────────────────

@pytest.fixture()
def buyer():
    from test_helpers import BUYER_HEADERS
    return BUYER_HEADERS


@pytest.fixture()
def som():
    from test_helpers import SOM_HEADERS
    return SOM_HEADERS


@pytest.fixture()
def planner():
    from test_helpers import PLANNER_HEADERS
    return PLANNER_HEADERS


@pytest.fixture()
def dco():
    from test_helpers import DCO_HEADERS
    return DCO_HEADERS


@pytest.fixture()
def importer():
    from test_helpers import IMPORT_HEADERS
    return IMPORT_HEADERS


@pytest.fixture()
def analyst():
    from test_helpers import ANALYST_HEADERS
    return ANALYST_HEADERS


@pytest.fixture()
def legal():
    from test_helpers import LEGAL_HEADERS
    return LEGAL_HEADERS


@pytest.fixture()
def admin():
    from test_helpers import ADMIN_HEADERS
    return ADMIN_HEADERS