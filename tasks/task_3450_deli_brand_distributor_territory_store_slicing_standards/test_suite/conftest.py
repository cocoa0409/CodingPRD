"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns PYTHONPATH, server lifecycle, and API_BASE_URL injection;
these fixtures only bridge the frozen helper layer into pytest.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def brand_admin_headers():
    return TEST_USERS["brand_admin_headers"]


@pytest.fixture
def distributor_rep_headers():
    return TEST_USERS["distributor_rep_headers"]


@pytest.fixture
def retail_manager_headers():
    return TEST_USERS["retail_manager_headers"]


@pytest.fixture
def plant_scheduler_headers():
    return TEST_USERS["plant_scheduler_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]
