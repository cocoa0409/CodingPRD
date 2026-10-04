"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def ledger_controller_headers():
    return TEST_USERS["ledger_controller_headers"]


@pytest.fixture
def payment_initiator_headers():
    return TEST_USERS["payment_initiator_headers"]


@pytest.fixture
def payment_approver_headers():
    return TEST_USERS["payment_approver_headers"]


@pytest.fixture
def payment_ops_analyst_headers():
    return TEST_USERS["payment_ops_analyst_headers"]


@pytest.fixture
def payment_ops_approver_headers():
    return TEST_USERS["payment_ops_approver_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]