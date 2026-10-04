"""Pytest fixture bridge exposing ``test_helpers`` infrastructure.

The runner owns server lifecycle and ``PYTHONPATH``; this module only turns the
shared API client and the pre-built role headers into pytest fixtures so test
modules can request them by name instead of importing module-level constants.

Role headers come straight from ``test_helpers.TEST_USERS``.  Six of the seven
roles are opaque — ``X-User-ID`` is an operator identifier that is never
compared to a persisted entity's ``id``.  ``Lessee`` is the exception: use
``make_lessee_headers(lessee["id"])`` for any ownership-gated call.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


# ─── One fixture per role in TEST_USERS ───────────────

@pytest.fixture
def platform_admin_headers() -> dict:
    """Opaque operator headers for the role that owns the logical clock."""
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def supply_chain_coordinator_headers() -> dict:
    """Opaque operator headers for the component catalogue and purchasing."""
    return TEST_USERS["supply_chain_coordinator_headers"]


@pytest.fixture
def production_planner_headers() -> dict:
    """Opaque operator headers for the order backlog and the line schedule."""
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def lease_administrator_headers() -> dict:
    """Opaque operator headers for contracts, placements and the return desk."""
    return TEST_USERS["lease_administrator_headers"]


@pytest.fixture
def portfolio_manager_headers() -> dict:
    """Opaque operator headers for sales, scrapping and return settlement."""
    return TEST_USERS["portfolio_manager_headers"]


@pytest.fixture
def regulatory_retrofitist_headers() -> dict:
    """Opaque operator headers for retrofit mandates and their coverage."""
    return TEST_USERS["regulatory_retrofitist_headers"]


@pytest.fixture
def lessee_headers() -> dict:
    """Non-owning ``Lessee`` headers.

    Only valid for calls whose success does not depend on owning the subject
    resource; ownership-gated reads need ``make_lessee_headers(lessee["id"])``.
    """
    return TEST_USERS["lessee_headers"]


# ─── Second operators ─────────────────────────────────
# Distinct operator identifiers, so the segregation-of-duties rule (the
# endorsement's creator may not be its approver) holds without extra setup.

@pytest.fixture
def production_planner_2_headers() -> dict:
    """A second planner operator, distinct from the first."""
    return TEST_USERS["production_planner_2_headers"]


@pytest.fixture
def lease_administrator_2_headers() -> dict:
    """A second lease administrator, distinct from the first."""
    return TEST_USERS["lease_administrator_2_headers"]


@pytest.fixture
def portfolio_manager_2_headers() -> dict:
    """A second portfolio manager, distinct from the first."""
    return TEST_USERS["portfolio_manager_2_headers"]


@pytest.fixture
def supply_chain_coordinator_2_headers() -> dict:
    """A second supply-chain operator, distinct from the first."""
    return TEST_USERS["supply_chain_coordinator_2_headers"]
