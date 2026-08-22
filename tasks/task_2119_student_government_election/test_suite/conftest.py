"""Pytest fixtures exposing the Student Government Election test helpers."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def commissioner_headers():
    return TEST_USERS["commissioner_headers"]


@pytest.fixture
def advisor_headers():
    return TEST_USERS["advisor_headers"]


@pytest.fixture
def second_advisor_headers():
    return TEST_USERS["second_advisor_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def candidate_headers():
    return TEST_USERS["candidate_headers"]


@pytest.fixture
def student_voter_headers():
    return TEST_USERS["student_voter_headers"]
