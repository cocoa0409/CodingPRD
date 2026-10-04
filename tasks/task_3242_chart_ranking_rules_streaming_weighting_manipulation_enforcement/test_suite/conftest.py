"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def chart_manager_headers():
    return TEST_USERS["chart_manager_headers"]


@pytest.fixture
def chart_ops_headers():
    return TEST_USERS["chart_ops_headers"]


@pytest.fixture
def investigator_headers():
    return TEST_USERS["investigator_headers"]


@pytest.fixture
def data_provider_headers():
    return TEST_USERS["data_provider_headers"]


@pytest.fixture
def label_rep_headers():
    return TEST_USERS["label_rep_headers"]
