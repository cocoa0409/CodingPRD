"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle and PYTHONPATH; every test starts
against a freshly restarted server (empty database, logical clock at the
PRD section 2.5 baseline). This module only bridges the helper layer into
pytest fixtures.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def society_admin_headers():
    return TEST_USERS["society_admin_headers"]


@pytest.fixture
def accreditation_reviewer_headers():
    return TEST_USERS["accreditation_reviewer_headers"]


@pytest.fixture
def accreditation_reviewer_2_headers():
    return TEST_USERS["accreditation_reviewer_2_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def consultant_headers():
    return TEST_USERS["consultant_headers"]


@pytest.fixture
def consultant_2_headers():
    return TEST_USERS["consultant_2_headers"]


@pytest.fixture
def school_admin_headers():
    """Fallback SchoolAdmin headers — valid only for tests that do NOT
    exercise entity-backed ownership."""
    return TEST_USERS["school_admin_headers"]


@pytest.fixture
def program_director_headers():
    """Fallback ProgramDirector headers — non-ownership tests only."""
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def adult_learner_headers():
    """Fallback AdultLearner headers — non-ownership tests only."""
    return TEST_USERS["adult_learner_headers"]


@pytest.fixture
def anonymous_headers():
    """The public caller carries no identity headers at all."""
    return TEST_USERS["anonymous_headers"]
