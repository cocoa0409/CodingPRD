"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the API server before every test, so every test starts
against an empty database (logical clock at the startup default
2026-09-01T00:00:00Z) and must build its own preconditions.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def applicant_headers():
    """Shared Applicant headers — only for tests that never exercise an
    ownership-gated resource. Ownership flows must instead build headers
    from the created applicant: make_applicant_headers(applicant["id"])."""
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def loan_officer_headers():
    return TEST_USERS["loan_officer_headers"]


@pytest.fixture
def loss_verifier_headers():
    return TEST_USERS["loss_verifier_headers"]


@pytest.fixture
def loan_approver_headers():
    return TEST_USERS["loan_approver_headers"]


@pytest.fixture
def servicing_agent_headers():
    return TEST_USERS["servicing_agent_headers"]


@pytest.fixture
def grant_coordinator_headers():
    return TEST_USERS["grant_coordinator_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
