"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable, manages the
server lifecycle, and injects API_BASE_URL before pytest starts.
"""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_assessor_headers,
    make_candidate_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def candidate_headers():
    """Shared Candidate headers — for non-ownership tests only. Use
    make_candidate_headers(candidate["id"]) for ownership-gated calls."""
    return TEST_USERS["candidate_headers"]


@pytest.fixture
def assessor_headers():
    """Shared Assessor headers — for non-ownership tests only. Use
    make_assessor_headers(assessor["id"]) for ownership-gated calls."""
    return TEST_USERS["assessor_headers"]


@pytest.fixture
def scoring_admin_headers():
    return TEST_USERS["scoring_admin_headers"]


@pytest.fixture
def board_admin_headers():
    return TEST_USERS["board_admin_headers"]


@pytest.fixture
def incentive_admin_headers():
    return TEST_USERS["incentive_admin_headers"]


@pytest.fixture
def candidate_headers_for():
    """Factory fixture: per-instance Candidate headers for the given
    Candidate.id (required for ownership-gated calls)."""
    return make_candidate_headers


@pytest.fixture
def assessor_headers_for():
    """Factory fixture: per-instance Assessor headers for the given
    Assessor.id (required for submit-score and assessor self-reads)."""
    return make_assessor_headers
