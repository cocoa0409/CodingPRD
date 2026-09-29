"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def broker_admin_headers():
    """Shared BrokerAdmin headers. Only for calls that are not ownership gated —
    ownership-gated calls must use make_broker_admin_headers(broker["id"])."""
    return TEST_USERS["broker_admin_headers"]


@pytest.fixture
def consumer_headers():
    """Shared Consumer headers. Only for calls that are not ownership gated —
    ownership-gated calls must use make_consumer_headers(consumer["id"])."""
    return TEST_USERS["consumer_headers"]


@pytest.fixture
def intake_agent_headers():
    return TEST_USERS["intake_agent_headers"]


@pytest.fixture
def privacy_reviewer_headers():
    """The reviewer who decides verifications in the standard setups."""
    return TEST_USERS["privacy_reviewer_headers"]


@pytest.fixture
def privacy_reviewer_beta_headers():
    """A second reviewer, used where the decider may not also execute."""
    return TEST_USERS["privacy_reviewer_beta_headers"]


@pytest.fixture
def state_platform_headers():
    return TEST_USERS["state_platform_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
