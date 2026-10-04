"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle, API_BASE_URL injection, and PYTHONPATH;
this module only bridges test_helpers into pytest fixtures.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    make_anonymous_headers,
    make_applicant_headers,
    make_campus_reviewer_headers,
    make_host_commission_headers,
    make_national_reviewer_headers,
    make_platform_admin_headers,
    make_program_officer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Shared role headers (one fixture per TEST_USERS entry)
# ---------------------------------------------------------------------------

@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def program_officer_headers():
    return TEST_USERS["program_officer_headers"]


@pytest.fixture
def host_commission_headers():
    return TEST_USERS["host_commission_headers"]


@pytest.fixture
def national_reviewer_headers():
    return TEST_USERS["national_reviewer_headers"]


@pytest.fixture
def national_reviewer_2_headers():
    return TEST_USERS["national_reviewer_2_headers"]


@pytest.fixture
def campus_reviewer_headers():
    return TEST_USERS["campus_reviewer_headers"]


@pytest.fixture
def campus_reviewer_2_headers():
    return TEST_USERS["campus_reviewer_2_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def applicant_headers():
    """Fallback Applicant identity for tests that do not exercise ownership.
    Ownership-gated calls must build headers from the real Applicant id via
    make_applicant_headers."""
    return TEST_USERS["applicant_headers"]


# ---------------------------------------------------------------------------
# Per-instance header builders
# ---------------------------------------------------------------------------

@pytest.fixture
def make_applicant_headers_factory():
    """Build ownership-correct Applicant headers: pass the Applicant id."""
    return make_applicant_headers


@pytest.fixture
def make_platform_admin_headers_factory():
    return make_platform_admin_headers


@pytest.fixture
def make_program_officer_headers_factory():
    return make_program_officer_headers


@pytest.fixture
def make_host_commission_headers_factory():
    return make_host_commission_headers


@pytest.fixture
def make_national_reviewer_headers_factory():
    return make_national_reviewer_headers


@pytest.fixture
def make_campus_reviewer_headers_factory():
    return make_campus_reviewer_headers


@pytest.fixture
def make_anonymous_headers_factory():
    return make_anonymous_headers
