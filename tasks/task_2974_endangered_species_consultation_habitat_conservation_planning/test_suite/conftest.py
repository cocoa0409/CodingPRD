"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    anonymous_headers,
    api_client,
    auditor_headers_without_user_id,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def registrar_headers():
    return TEST_USERS["agency_registrar_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["agency_reviewer_headers"]


@pytest.fixture
def issuer_headers():
    return TEST_USERS["agency_issuer_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["agency_approver_headers"]


@pytest.fixture
def adjudicator_headers():
    return TEST_USERS["agency_adjudicator_headers"]


@pytest.fixture
def auditor_headers():
    return auditor_headers_without_user_id()


@pytest.fixture
def anon_headers():
    return anonymous_headers()
