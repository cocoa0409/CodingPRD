"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def trend_scout_headers():
    return TEST_USERS["trend_scout_headers"]


@pytest.fixture
def product_manager_headers():
    return TEST_USERS["product_manager_headers"]


@pytest.fixture
def sourcing_lead_headers():
    return TEST_USERS["sourcing_lead_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def retail_planner_headers():
    return TEST_USERS["retail_planner_headers"]


@pytest.fixture
def marketing_lead_headers():
    return TEST_USERS["marketing_lead_headers"]


@pytest.fixture
def manufacturer_rep_headers():
    """Shared ManufacturerRep identity — non-ownership contexts only. For
    ownership-gated calls use make_manufacturer_rep_headers(cm_id)."""
    return TEST_USERS["manufacturer_rep_headers"]
