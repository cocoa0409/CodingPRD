"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; these fixtures only bridge
the shared client and the role-header constants into test modules.  The
autouse ``logical_clock`` fixture re-pins the server clock to its documented
default (2026-09-01T00:00:00Z) before each test so deadline arithmetic is
deterministic even if the server process is shared.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    make_admin_headers,
    make_board_headers,
    reset_clock,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is the runner's."""
    return api_client


@pytest.fixture(autouse=True)
def logical_clock():
    """Reset the logical clock to its default before every test."""
    reset_clock()
    yield


@pytest.fixture
def admin_headers() -> dict:
    """CourtAdministrator headers (opaque identity)."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def board_headers() -> dict:
    """BoardMember headers (opaque identity)."""
    return TEST_USERS["board_headers"]


@pytest.fixture
def judge_headers() -> dict:
    """ImmigrationJudge headers bound to NO existing Judge — usable ONLY for
    the unresolvable-identity 400 path.  Successful judge calls must build
    headers from a real Judge id via ``make_judge_headers(judge['id'])``."""
    return TEST_USERS["judge_headers"]


@pytest.fixture
def make_headers():
    """Header builder factory: (user_id, role) -> headers dict."""
    from test_helpers import build_user_headers

    return build_user_headers


@pytest.fixture
def admin_header_factory():
    return make_admin_headers


@pytest.fixture
def board_header_factory():
    return make_board_headers
