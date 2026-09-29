"""Pytest fixtures exposing ``test_helpers`` infrastructure.

The runner restarts the server before every individual test, so each test sees
an empty database and the logical clock at its configured start
(``2026-08-01T00:00:00Z``, PRD §2.4).  Nothing here needs to clean up.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client
from test_helpers import fixtures as fx


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is the runner's job."""
    return api_client


# ─── Opaque-identity role headers (PRD §2.1) ───────────────────────────
@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin2_headers():
    """A second AgencyAdmin, for the §2.8 appeal segregation rule."""
    return TEST_USERS["admin2_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def supervisor2_headers():
    """A second LicensingSupervisor, for the §2.8 segregation rules."""
    return TEST_USERS["supervisor2_headers"]


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def bgu_headers():
    return TEST_USERS["bgu_headers"]


@pytest.fixture
def public_headers():
    return TEST_USERS["public_headers"]


# ─── Shared domain state ───────────────────────────────────────────────
@pytest.fixture
def catalog(api):
    """The statutory checklist catalogue, as ``{code: checklist_item_id}``."""
    return fx.seed_catalog(api)


@pytest.fixture
def inspector(api):
    """An ACTIVE inspector certified for every age group."""
    return fx.register_inspector(api)
