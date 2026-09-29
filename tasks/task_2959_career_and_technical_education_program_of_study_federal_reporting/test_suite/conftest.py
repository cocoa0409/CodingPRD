"""Pytest fixtures exposing the shared CTE test infrastructure.

The runner restarts the API server before every individual test, so each test
begins against an empty database with the logical clock at its startup default
of 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    Builder,
    CteApiClient,
    register_error_http_statuses,
    users,
)

register_error_http_statuses()


@pytest.fixture()
def api() -> CteApiClient:
    """HTTP client for the API under test; the runner owns the server lifecycle."""
    return CteApiClient()


@pytest.fixture()
def build(api: CteApiClient) -> Builder:
    """Scenario builder that drives the public API to reach a starting state."""
    return Builder(api)


@pytest.fixture()
def director_headers():
    """Headers for the primary CteDirector operator."""
    return users.headers(users.DIRECTOR)


@pytest.fixture()
def director_two_headers():
    """Headers for a second, distinct CteDirector operator."""
    return users.headers(users.DIRECTOR_TWO)


@pytest.fixture()
def reviewer_headers():
    """Headers for the primary StateComplianceReviewer operator."""
    return users.headers(users.REVIEWER)


@pytest.fixture()
def reviewer_two_headers():
    """Headers for a second, distinct StateComplianceReviewer operator."""
    return users.headers(users.REVIEWER_TWO)


@pytest.fixture()
def fiscal_headers():
    """Headers for the primary GrantFiscalOfficer operator."""
    return users.headers(users.FISCAL_OFFICER)


@pytest.fixture()
def fiscal_two_headers():
    """Headers for a second, distinct GrantFiscalOfficer operator."""
    return users.headers(users.FISCAL_OFFICER_TWO)


@pytest.fixture()
def registrar_headers():
    """Headers for the SchoolRegistrar operator."""
    return users.headers(users.REGISTRAR)
