"""Pytest fixtures exposing the test_helpers infrastructure.

The API server is restarted by the runner before every individual test, so each
test starts from an empty database and builds whatever state it needs through the
public endpoints.  The two entity-backed roles have no fixture here: their acting
user identifier IS the seller's or the advertiser's own identifier, so a test
builds their headers with ``make_seller_rep_headers`` /
``make_advertiser_client_headers`` once that entity exists.
"""

import pytest

from test_helpers import (
    BUYER_ALT_HEADERS,
    BUYER_HEADERS,
    CONTROLLER_ALT_HEADERS,
    CONTROLLER_HEADERS,
    EMPTY_USER_ID_HEADERS,
    MEASUREMENT_HEADERS,
    NO_AUTH_HEADERS,
    NO_ROLE_HEADERS,
    PLANNER_ALT_HEADERS,
    PLANNER_HEADERS,
    UNDECLARED_ROLE_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def planner_headers():
    """The agency planner who builds the channel plan and submits it."""
    return PLANNER_HEADERS


@pytest.fixture
def second_planner_headers():
    """A second agency planner."""
    return PLANNER_ALT_HEADERS


@pytest.fixture
def buyer_headers():
    """The agency buyer who negotiates, places buys and adjudicates delivery."""
    return BUYER_HEADERS


@pytest.fixture
def second_buyer_headers():
    """A second agency buyer."""
    return BUYER_ALT_HEADERS


@pytest.fixture
def controller_headers():
    """The agency controller who onboards counterparties and drives billing."""
    return CONTROLLER_HEADERS


@pytest.fixture
def second_controller_headers():
    """A second controller, required wherever remittance is segregated."""
    return CONTROLLER_ALT_HEADERS


@pytest.fixture
def measurement_headers():
    """The independent measurement vendor that files delivery."""
    return MEASUREMENT_HEADERS


@pytest.fixture
def unauthenticated_headers():
    """Headers carrying neither identity header."""
    return NO_AUTH_HEADERS


@pytest.fixture
def no_role_headers():
    """Headers carrying an acting user but no role."""
    return NO_ROLE_HEADERS


@pytest.fixture
def undeclared_role_headers():
    """Headers naming a role outside the declared set."""
    return UNDECLARED_ROLE_HEADERS


@pytest.fixture
def empty_user_id_headers():
    """Headers carrying a role but an empty acting user identifier."""
    return EMPTY_USER_ID_HEADERS
