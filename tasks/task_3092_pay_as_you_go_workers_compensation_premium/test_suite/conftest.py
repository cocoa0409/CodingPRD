"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle (start/stop/restart per test) is owned by prd-bench-local-runner;
this module only wires the generated helpers into pytest fixtures.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client pointing at API_BASE_URL."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def payroll_provider_headers():
    return TEST_USERS["payroll_provider_headers"]


@pytest.fixture
def tax_filer_headers():
    return TEST_USERS["tax_filer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def employer_admin_headers():
    """Fallback EmployerAdmin identity for requests that are not ownership-gated."""
    return TEST_USERS["employer_admin_headers"]
