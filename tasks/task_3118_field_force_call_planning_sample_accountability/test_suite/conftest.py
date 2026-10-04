"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    COMPLIANCE_HEADERS,
    DISTRICT_MANAGER_HEADERS,
    FIELD_REP_HEADERS,
    QA_HEADERS,
    ApiClient,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  The server lifecycle is managed by the
    runner; this suite only talks to the already-running server."""
    return ApiClient()


@pytest.fixture
def admin_headers():
    return ADMIN_HEADERS


@pytest.fixture
def compliance_headers():
    return COMPLIANCE_HEADERS


@pytest.fixture
def qa_headers():
    return QA_HEADERS


@pytest.fixture
def district_manager_headers():
    return DISTRICT_MANAGER_HEADERS


@pytest.fixture
def field_rep_headers():
    return FIELD_REP_HEADERS
