"""
Shared pytest fixtures.

The server is restarted before every test, so there is deliberately no state-bearing
fixture here: the only session-scoped object is the HTTP client itself. Everything a
test needs in the store is built inside the test through the scenario builders in
`test_helpers.fixtures`, which go through the public endpoints like any other client.
"""

import pytest

from test_helpers import (
    AHJ_2_HEADERS,
    AHJ_HEADERS,
    REBATE_ADMIN_2_HEADERS,
    REBATE_ADMIN_HEADERS,
    UTILITY_REVIEWER_2_HEADERS,
    UTILITY_REVIEWER_HEADERS,
    WARRANTY_AGENT_2_HEADERS,
    WARRANTY_AGENT_HEADERS,
    api_client,
)


@pytest.fixture(scope="session")
def api():
    """The HTTP client, one method per declared operation."""
    return api_client


@pytest.fixture
def warranty_agent():
    """The manufacturer's certification and warranty desk."""
    return WARRANTY_AGENT_HEADERS


@pytest.fixture
def second_warranty_agent():
    """A second warranty-desk operator, for two-person scenarios."""
    return WARRANTY_AGENT_2_HEADERS


@pytest.fixture
def ahj():
    """The building and electrical authority."""
    return AHJ_HEADERS


@pytest.fixture
def second_ahj():
    """A second authority operator."""
    return AHJ_2_HEADERS


@pytest.fixture
def utility_reviewer():
    """Utility distributed-energy staff; the operator who reviews applications."""
    return UTILITY_REVIEWER_HEADERS


@pytest.fixture
def second_utility_reviewer():
    """A second utility operator, who is the one allowed to grant permission to operate."""
    return UTILITY_REVIEWER_2_HEADERS


@pytest.fixture
def rebate_admin():
    """The incentive administrator who creates programs and adjudicates claims."""
    return REBATE_ADMIN_HEADERS


@pytest.fixture
def second_rebate_admin():
    """A second administrator, who is the one allowed to release payment."""
    return REBATE_ADMIN_2_HEADERS
