"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle, API_BASE_URL injection, and PYTHONPATH;
these fixtures only bridge the pre-built helpers into tests.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def program_admin_2_headers():
    return TEST_USERS["program_admin_2_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def score_analyst_headers():
    return TEST_USERS["score_analyst_headers"]
