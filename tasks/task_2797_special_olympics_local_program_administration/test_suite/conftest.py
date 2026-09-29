"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import (
    OFFICERS,
    REVIEWERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def credentialing_officer_headers():
    return TEST_USERS["credentialing_officer_headers"]


@pytest.fixture
def medical_reviewer_headers():
    return TEST_USERS["medical_reviewer_headers"]


@pytest.fixture
def coach_headers():
    """Shared Coach constant: only for tests that do not exercise ownership."""
    return TEST_USERS["coach_headers"]


@pytest.fixture
def competition_director_headers():
    return TEST_USERS["competition_director_headers"]


@pytest.fixture
def health_screening_lead_headers():
    return TEST_USERS["health_screening_lead_headers"]


@pytest.fixture
def officers():
    return OFFICERS


@pytest.fixture
def reviewers():
    return REVIEWERS
