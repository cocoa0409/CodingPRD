"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ANALYST_DRAFTER,
    ANALYST_ISSUER,
    COMPLIANCE_AUDITOR,
    COMPLIANCE_SCREENER,
    PLATFORM_ADMIN,
    VALET_OPS_MANAGER,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return PLATFORM_ADMIN


@pytest.fixture
def ops_headers():
    return VALET_OPS_MANAGER


@pytest.fixture
def screener_headers():
    return COMPLIANCE_SCREENER


@pytest.fixture
def auditor_headers():
    return COMPLIANCE_AUDITOR


@pytest.fixture
def drafter_headers():
    return ANALYST_DRAFTER


@pytest.fixture
def issuer_headers():
    return ANALYST_ISSUER
