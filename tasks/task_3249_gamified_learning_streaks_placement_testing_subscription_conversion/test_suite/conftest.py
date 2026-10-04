"""Pytest fixture bridge exposing ``test_helpers`` infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client, make_learner_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def proctor_headers():
    return TEST_USERS["proctor_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def learner_headers():
    """Fallback headers for the Learner role.

    Only for calls that do not exercise ownership; ownership-gated calls must use
    ``make_learner_headers(<learner id>)`` with the entity's own id.
    """
    return TEST_USERS["learner_headers"]


@pytest.fixture
def learner_factory():
    """Build ownership-correct Learner headers for a minted learner id."""
    return make_learner_headers