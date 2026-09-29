"""Pytest fixtures exposing the shared test infrastructure.

The API server lifecycle belongs to the runner, which restarts the process
before every test, so each test opens against an empty county register and every
precondition below is built from scratch through the public endpoints.
"""

import pytest

from test_helpers import (
    ADMIN,
    ANALYST,
    CLERK,
    HEARING_CLERK,
    HEARING_OFFICER,
    INVESTIGATOR,
    RECOVERY,
    REVIEWER,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def users():
    """Headers for one acting operator per non-taxpayer role."""
    return TEST_USERS


@pytest.fixture
def admin_headers():
    return ADMIN


@pytest.fixture
def analyst_headers():
    return ANALYST


@pytest.fixture
def clerk_headers():
    return CLERK


@pytest.fixture
def reviewer_headers():
    return REVIEWER


@pytest.fixture
def investigator_headers():
    return INVESTIGATOR


@pytest.fixture
def recovery_headers():
    return RECOVERY


@pytest.fixture
def hearing_clerk_headers():
    return HEARING_CLERK


@pytest.fixture
def hearing_officer_headers():
    return HEARING_OFFICER
