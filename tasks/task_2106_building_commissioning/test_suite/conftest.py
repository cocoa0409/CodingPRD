"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def cx_authority_headers():
    return TEST_USERS["cx_authority_headers"]


@pytest.fixture
def cx_authority_alt_headers():
    return TEST_USERS["cx_authority_alt_headers"]


@pytest.fixture
def contractor_headers():
    return TEST_USERS["contractor_headers"]


@pytest.fixture
def design_team_headers():
    return TEST_USERS["design_team_headers"]


@pytest.fixture
def owner_representative_headers():
    return TEST_USERS["owner_representative_headers"]
