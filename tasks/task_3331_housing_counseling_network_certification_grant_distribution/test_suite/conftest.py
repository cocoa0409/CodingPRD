"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_network_director_headers, make_assessor_headers,
    make_training_registrar_headers, make_grant_officer_headers,
    make_member_admin_headers, make_compliance_reviewer_headers,
    make_auditor_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def network_director_headers():
    return TEST_USERS["network_director_headers"]


@pytest.fixture
def assessor_headers():
    return TEST_USERS["assessor_headers"]


@pytest.fixture
def training_registrar_headers():
    return TEST_USERS["training_registrar_headers"]


@pytest.fixture
def grant_officer_headers():
    return TEST_USERS["grant_officer_headers"]


@pytest.fixture
def member_admin_headers():
    return TEST_USERS["member_admin_headers"]


@pytest.fixture
def compliance_reviewer_headers():
    return TEST_USERS["compliance_reviewer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
