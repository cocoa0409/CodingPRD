"""
Shared pytest fixtures for the child-support establishment and enforcement suite.

The harness owns the server lifecycle and restarts the API before every single
test, so every fixture here is function-scoped and no state is shared across
tests. Each test builds its own preconditions through the documented endpoints.
"""

from typing import Dict

import pytest

from test_helpers.api_client import ApiClient, api_client
from test_helpers.test_users import (
    CASE_WORKER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    INTERSTATE_LIAISON_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    SUPERVISING_ATTORNEY_HEADERS,
    TEST_USERS,
)


@pytest.fixture()
def api() -> ApiClient:
    """The HTTP client bound to the base URL the harness exported."""
    return api_client


@pytest.fixture()
def case_worker_headers() -> Dict[str, str]:
    """Headers for a `CaseWorker`, who runs establishment and enforcement casework."""
    return dict(CASE_WORKER_HEADERS)


@pytest.fixture()
def supervising_attorney_headers() -> Dict[str, str]:
    """Headers for a `SupervisingAttorney`, who makes the judicial-side decisions."""
    return dict(SUPERVISING_ATTORNEY_HEADERS)


@pytest.fixture()
def finance_officer_headers() -> Dict[str, str]:
    """Headers for a `FinanceOfficer`, who owns the ledger and settlements."""
    return dict(FINANCE_OFFICER_HEADERS)


@pytest.fixture()
def interstate_liaison_headers() -> Dict[str, str]:
    """Headers for an `InterstateLiaison`, who works the two-state channel."""
    return dict(INTERSTATE_LIAISON_HEADERS)


@pytest.fixture()
def program_admin_headers() -> Dict[str, str]:
    """Headers for a `ProgramAdmin`, who runs the registries and the logical clock."""
    return dict(PROGRAM_ADMIN_HEADERS)


@pytest.fixture()
def headers_for_role():
    """Build headers for any of the roles that are not backed by a stored entity."""

    def _build(role: str) -> Dict[str, str]:
        return dict(TEST_USERS[role])

    return _build
