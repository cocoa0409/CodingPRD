"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is owned by prd-bench-local-runner, which restarts the API
server via start.sh before every individual test: each test therefore starts
against an empty database and must build every precondition itself.
"""
import pytest

from test_helpers import ApiClient, api_client, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def enrollment_ops_headers():
    return TEST_USERS["enrollment_ops_headers"]


@pytest.fixture
def clinical_ops_headers():
    return TEST_USERS["clinical_ops_headers"]


@pytest.fixture
def billing_ops_headers():
    return TEST_USERS["billing_ops_headers"]


@pytest.fixture
def eligibility_service_headers():
    return TEST_USERS["eligibility_service_headers"]


@pytest.fixture
def outreach_service_headers():
    return TEST_USERS["outreach_service_headers"]


@pytest.fixture
def clinical_review_service_headers():
    return TEST_USERS["clinical_review_service_headers"]


@pytest.fixture
def clinician_headers():
    return TEST_USERS["clinician_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]