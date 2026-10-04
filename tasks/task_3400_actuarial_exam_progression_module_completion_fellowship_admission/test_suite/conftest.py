"""Pytest fixtures exposing test_helpers infrastructure.

Stage 5a scope: helpers only — no test files are generated in this stage.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def candidate_headers():
    return TEST_USERS["candidate_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def exam_committee_headers():
    return TEST_USERS["exam_committee_headers"]


@pytest.fixture
def academic_reviewer_headers():
    return TEST_USERS["academic_reviewer_headers"]


@pytest.fixture
def grader_headers():
    return TEST_USERS["grader_headers"]


@pytest.fixture
def discipline_board_headers():
    return TEST_USERS["discipline_board_headers"]
