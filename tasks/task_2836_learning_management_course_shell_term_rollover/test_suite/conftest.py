"""Shared pytest fixtures.

The runner owns the server lifecycle: it relaunches the process before every
individual test, so each test body sees an empty database and must build its own
preconditions through the PRD's endpoints.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_helpers import ApiClient, TEST_USERS  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    make_accessibility_reviewer_headers,
    make_instructor_headers,
    make_lms_admin_headers,
    make_privacy_reviewer_headers,
    make_registrar_headers,
    make_student_headers,
)


@pytest.fixture(scope="session")
def api():
    """The domain API client (one method per endpoint in the PRD)."""
    return ApiClient()


# ─── opaque operator roles ────────────────────────────────────────────────

@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def registrar_alt_headers():
    return TEST_USERS["registrar_alt_headers"]


@pytest.fixture
def lms_admin_headers():
    return TEST_USERS["lms_admin_headers"]


@pytest.fixture
def lms_admin_alt_headers():
    return TEST_USERS["lms_admin_alt_headers"]


@pytest.fixture
def privacy_reviewer_headers():
    return TEST_USERS["privacy_reviewer_headers"]


@pytest.fixture
def privacy_reviewer_alt_headers():
    return TEST_USERS["privacy_reviewer_alt_headers"]


@pytest.fixture
def accessibility_reviewer_headers():
    return TEST_USERS["accessibility_reviewer_headers"]


@pytest.fixture
def accessibility_reviewer_alt_headers():
    return TEST_USERS["accessibility_reviewer_alt_headers"]


# ─── person-backed roles ──────────────────────────────────────────────────

@pytest.fixture
def instructor_headers():
    """Unbound Instructor headers — only for calls with no ownership check."""
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def student_headers():
    """Unbound Student headers — only for calls with no ownership check."""
    return TEST_USERS["student_headers"]


@pytest.fixture
def instructor_headers_for():
    """Factory: Instructor headers bound to a real Person.id."""
    return make_instructor_headers


@pytest.fixture
def student_headers_for():
    """Factory: Student headers bound to a real Person.id."""
    return make_student_headers


@pytest.fixture
def registrar_headers_for():
    return make_registrar_headers


@pytest.fixture
def lms_admin_headers_for():
    return make_lms_admin_headers


@pytest.fixture
def privacy_reviewer_headers_for():
    return make_privacy_reviewer_headers


@pytest.fixture
def accessibility_reviewer_headers_for():
    return make_accessibility_reviewer_headers
