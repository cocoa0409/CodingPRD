"""Pytest fixtures exposing the test_helpers infrastructure.

The runner restarts the API server before every test and injects
``API_BASE_URL`` into the environment; the client constructor reads it, so no
port or URL appears here. The client fixture is function-scoped: a fresh
``requests.Session`` per test avoids stale keep-alive connections against a
server that was just restarted.
"""

import pytest

from test_helpers import (
    DISTRICT_MANAGER_HEADERS,
    LABEL_OFFICER_HEADERS,
    PROGRAM_ADMINISTRATOR_HEADERS,
    RECALL_COORDINATOR_HEADERS,
    TEST_USERS,
    ApiClient,
)


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test. Server lifecycle is managed
    by the runner; tests never start or stop it."""
    return ApiClient()


# ── Opaque-role headers (never matched against an entity) ────────────────────

@pytest.fixture()
def district_manager_headers() -> dict:
    return DISTRICT_MANAGER_HEADERS


@pytest.fixture()
def label_officer_headers() -> dict:
    return LABEL_OFFICER_HEADERS


@pytest.fixture()
def recall_coordinator_headers() -> dict:
    return RECALL_COORDINATOR_HEADERS


@pytest.fixture()
def program_administrator_headers() -> dict:
    return PROGRAM_ADMINISTRATOR_HEADERS


# ── Fallback entity-backed headers (non-ownership tests ONLY) ────────────────
# For any ownership- or segregation-gated call, tests must instead use
# make_establishment_manager_headers / make_inspector_headers /
# make_supervisory_reviewer_headers with the real entity id.

@pytest.fixture()
def establishment_manager_headers() -> dict:
    return TEST_USERS["establishment_manager_headers"]


@pytest.fixture()
def inspector_headers() -> dict:
    return TEST_USERS["inspector_headers"]


@pytest.fixture()
def supervisory_reviewer_headers() -> dict:
    return TEST_USERS["supervisory_reviewer_headers"]
