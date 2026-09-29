"""Pytest fixtures, tiered from the bare client up to a case in ARBITRATOR_REVIEW.

The harness restarts the service before every test, so every fixture builds its
state from an empty database through the PRD's own endpoints.
"""
import pytest

from .api_client import ArbitrationApiClient
from .constants import FRAME_DAMAGE_POLICY, MECHANICAL_POLICY
from .factories import (
    build_arbitrator_review_world,
    build_case_world,
    build_negotiation_world,
    build_registry,
    build_sale_world,
    build_under_review_world,
)


# --- Tier 1: the client -------------------------------------------------------


@pytest.fixture
def api() -> ArbitrationApiClient:
    return ArbitrationApiClient()


# --- Tier 2: the registry -----------------------------------------------------


@pytest.fixture
def registry(api):
    """A seller, a buyer and the MECHANICAL policy."""
    return build_registry(api, [MECHANICAL_POLICY])


@pytest.fixture
def two_policy_registry(api):
    """A seller, a buyer and both the MECHANICAL and FRAME_DAMAGE policies."""
    return build_registry(api, [MECHANICAL_POLICY, FRAME_DAMAGE_POLICY])


# --- Tier 3: a recorded sale --------------------------------------------------


@pytest.fixture
def sale_world(api):
    """Registry plus one sale recorded at the clock's startup default."""
    return build_sale_world(api, [MECHANICAL_POLICY])


@pytest.fixture
def two_policy_sale_world(api):
    return build_sale_world(api, [MECHANICAL_POLICY, FRAME_DAMAGE_POLICY])


# --- Tier 4: a filed claim ----------------------------------------------------


@pytest.fixture
def case_world(api):
    """A MECHANICAL claim in SUBMITTED on an unsettled sale."""
    return build_case_world(api, [MECHANICAL_POLICY])


@pytest.fixture
def under_review_world(api):
    """The same claim carried to UNDER_REVIEW with a verified inspection report."""
    return build_under_review_world(api, [MECHANICAL_POLICY])


# --- Tier 5: negotiation and adjudication ------------------------------------


@pytest.fixture
def negotiation_world(api):
    """A case in NEGOTIATION with one OPEN 200000-cent allowance offer."""
    return build_negotiation_world(api, seller_offer_cents=200000)


@pytest.fixture
def disputed_world(api):
    """A case in ARBITRATOR_REVIEW because the consignor disputed the claim."""
    return build_arbitrator_review_world(api, response_type="DISPUTE")


@pytest.fixture
def conceded_world(api):
    """A case in ARBITRATOR_REVIEW with seller_conceded true."""
    return build_arbitrator_review_world(api, response_type="ACCEPT_UNWIND")
