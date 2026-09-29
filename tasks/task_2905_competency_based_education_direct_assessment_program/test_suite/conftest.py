"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def integrity_officer_headers():
    return TEST_USERS["integrity_officer_headers"]


@pytest.fixture
def financial_aid_officer_headers():
    return TEST_USERS["financial_aid_officer_headers"]


@pytest.fixture
def student_headers():
    """Shared Student identity. Ownership-gated calls must instead use
    make_student_headers() with the real student's id."""
    return TEST_USERS["student_headers"]


@pytest.fixture
def faculty_mentor_headers():
    """Shared FacultyMentor identity. Ownership-gated calls must instead use
    make_mentor_headers() with the real mentor's id."""
    return TEST_USERS["faculty_mentor_headers"]


@pytest.fixture
def evaluator_headers():
    """Shared Evaluator identity. Ownership-gated calls must instead use
    make_evaluator_headers() with the real evaluator's id."""
    return TEST_USERS["evaluator_headers"]
