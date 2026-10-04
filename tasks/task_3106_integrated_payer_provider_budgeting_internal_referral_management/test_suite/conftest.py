"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; this file only wires the
shared API client and the role header sets into pytest.
"""

import pytest

from test_helpers import api_client, ApiClient, TEST_USERS, make_provider_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def rfo_headers():
    return TEST_USERS["regional_finance_officer_headers"]


@pytest.fixture
def ur_headers():
    return TEST_USERS["utilization_reviewer_headers"]


@pytest.fixture
def as_headers():
    return TEST_USERS["access_scheduler_headers"]


@pytest.fixture
def qrb_headers():
    return TEST_USERS["quality_review_board_headers"]


@pytest.fixture
def bac_headers():
    return TEST_USERS["budget_appropriations_committee_headers"]


@pytest.fixture
def ctm_headers():
    return TEST_USERS["care_team_member_headers"]


@pytest.fixture
def provider_headers():
    return TEST_USERS["provider_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def make_provider_role_headers():
    """Builder for the entity-backed Provider role; pass the Provider.id."""
    return make_provider_headers