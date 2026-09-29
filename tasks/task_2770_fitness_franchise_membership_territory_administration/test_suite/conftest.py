"""Pytest fixtures exposing the franchise test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def brand_administrator_headers():
    return TEST_USERS["brand_administrator_headers"]


@pytest.fixture
def brand_administrator_alt_headers():
    return TEST_USERS["brand_administrator_alt_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def compliance_auditor_alt_headers():
    return TEST_USERS["compliance_auditor_alt_headers"]


@pytest.fixture
def billing_partner_headers():
    return TEST_USERS["billing_partner_headers"]


@pytest.fixture
def franchise_owner_headers():
    return TEST_USERS["franchise_owner_headers"]


@pytest.fixture
def club_manager_headers():
    return TEST_USERS["club_manager_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
