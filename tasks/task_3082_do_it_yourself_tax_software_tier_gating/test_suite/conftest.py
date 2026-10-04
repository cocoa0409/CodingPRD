"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def taxpayer_headers():
    """Fallback Taxpayer headers (bootstrap only — ownership-gated calls must
    use make_taxpayer_headers with the real account id)."""
    return TEST_USERS["taxpayer_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def platform_operator_headers():
    return TEST_USERS["platform_operator_headers"]
