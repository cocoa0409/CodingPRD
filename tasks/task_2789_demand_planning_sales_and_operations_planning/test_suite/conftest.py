"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def sop_admin_headers():
    return TEST_USERS["sop_admin_headers"]


@pytest.fixture
def demand_planner_headers():
    return TEST_USERS["demand_planner_headers"]


@pytest.fixture
def demand_review_lead_headers():
    return TEST_USERS["demand_review_lead_headers"]


@pytest.fixture
def supply_planner_headers():
    return TEST_USERS["supply_planner_headers"]


@pytest.fixture
def executive_sponsor_headers():
    return TEST_USERS["executive_sponsor_headers"]


@pytest.fixture
def customer_rep_headers():
    """A CustomerRep identity not bound to any real customer. Ownership-gated
    reads must build their headers from the acting customer's own id instead."""
    return TEST_USERS["customer_rep_headers"]
