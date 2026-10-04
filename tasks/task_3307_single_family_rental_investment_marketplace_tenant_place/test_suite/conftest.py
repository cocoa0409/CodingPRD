"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    CLAIMS_ADJUSTER_HEADERS,
    ESCROW_OFFICER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    REVIEWER_HEADERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return PLATFORM_ADMIN_HEADERS


@pytest.fixture
def reviewer_headers():
    return REVIEWER_HEADERS


@pytest.fixture
def escrow_officer_headers():
    return ESCROW_OFFICER_HEADERS


@pytest.fixture
def claims_adjuster_headers():
    return CLAIMS_ADJUSTER_HEADERS
