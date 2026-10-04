"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def gse_admin_headers():
    return TEST_USERS["gse_admin_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def uw_engine_headers():
    return TEST_USERS["uw_engine_headers"]


@pytest.fixture
def qc_auditor_headers():
    return TEST_USERS["qc_auditor_headers"]
