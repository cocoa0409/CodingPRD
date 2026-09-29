"""Pytest fixtures exposing the shellfish test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def authority_headers():
    """`ShellfishControlAuthority` — opaque operator identifier."""
    return TEST_USERS["authority_headers"]


@pytest.fixture
def reviewer_headers():
    """`SitingReviewer` — opaque reviewer identifier."""
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def reviewer_b_headers():
    """A second, distinct `SitingReviewer` identity."""
    return TEST_USERS["reviewer_b_headers"]


@pytest.fixture
def operator_headers():
    """`FarmOperator` — the identity recorded as a lease's operator_user_id."""
    return TEST_USERS["operator_headers"]


@pytest.fixture
def operator_b_headers():
    """A second, distinct `FarmOperator` identity — never a lease owner."""
    return TEST_USERS["operator_b_headers"]


@pytest.fixture
def hatchery_operator_headers():
    """`HatcheryOperator` with a placeholder identifier — only safe where
    ownership is not the rule under test."""
    return TEST_USERS["hatchery_operator_headers"]


@pytest.fixture
def seafood_dealer_headers():
    """`SeafoodDealer` with a placeholder identifier — only safe where ownership
    is not the rule under test."""
    return TEST_USERS["seafood_dealer_headers"]
