"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the runner manages server lifecycle."""
    return api_client


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def submitter_headers():
    return TEST_USERS["submitter_headers"]


@pytest.fixture
def certifier_headers():
    return TEST_USERS["certifier_headers"]


@pytest.fixture
def requester_headers():
    return TEST_USERS["requester_headers"]


@pytest.fixture
def learner_headers():
    return TEST_USERS["learner_headers"]


@pytest.fixture
def servicer_headers():
    return TEST_USERS["servicer_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]
