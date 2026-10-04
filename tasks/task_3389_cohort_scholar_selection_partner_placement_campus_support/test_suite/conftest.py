"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH: the API under test is
already reachable at API_BASE_URL, and ``test_helpers`` is importable as a
top-level package. These fixtures are thin bridges only — entity-backed
identities (Nominator -> NominatingPartner.id, Nominee -> Nominee.id,
FacultyMentor -> Mentor.id, Scholar -> Scholar.id) are built per-test with
``make_*_headers`` from test_helpers, never from the shared fallback
constants, whenever the call is ownership-gated (PRD §2.1).
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def assessor_a_headers():
    return TEST_USERS["assessor_a_headers"]


@pytest.fixture
def assessor_b_headers():
    return TEST_USERS["assessor_b_headers"]


@pytest.fixture
def selection_officer_headers():
    return TEST_USERS["selection_officer_headers"]


@pytest.fixture
def career_director_headers():
    return TEST_USERS["career_director_headers"]


@pytest.fixture
def nominator_headers():
    """Fallback only — never equals a real NominatingPartner.id. For
    ownership-gated calls use make_nominator_headers(partner["id"])."""
    return TEST_USERS["nominator_headers"]


@pytest.fixture
def nominee_headers():
    """Fallback only — never equals a real Nominee.id. For offer accept/
    decline use make_nominee_headers(offer["nominee_id"])."""
    return TEST_USERS["nominee_headers"]


@pytest.fixture
def faculty_mentor_headers():
    """Fallback only — never equals a real Mentor.id. For meeting logging use
    make_faculty_mentor_headers(mentor["id"])."""
    return TEST_USERS["faculty_mentor_headers"]


@pytest.fixture
def scholar_headers():
    """Fallback only — never equals a real Scholar.id. For self-lifecycle use
    make_scholar_headers(scholar["id"])."""
    return TEST_USERS["scholar_headers"]
