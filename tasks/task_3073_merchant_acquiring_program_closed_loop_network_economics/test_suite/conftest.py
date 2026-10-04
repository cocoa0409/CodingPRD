"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle (a fresh server per test) — these fixtures
only wire up the API client and the role headers.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def network_acquirer_headers():
    return TEST_USERS["network_acquirer_headers"]


@pytest.fixture
def network_settlement_ops_headers():
    return TEST_USERS["network_settlement_ops_headers"]


@pytest.fixture
def network_compliance_headers():
    return TEST_USERS["network_compliance_headers"]


@pytest.fixture
def network_data_steward_headers():
    return TEST_USERS["network_data_steward_headers"]


@pytest.fixture
def network_dispute_ops_headers():
    return TEST_USERS["network_dispute_ops_headers"]


@pytest.fixture
def network_service_headers():
    return TEST_USERS["network_service_headers"]


@pytest.fixture
def network_issuer_headers():
    return TEST_USERS["network_issuer_headers"]