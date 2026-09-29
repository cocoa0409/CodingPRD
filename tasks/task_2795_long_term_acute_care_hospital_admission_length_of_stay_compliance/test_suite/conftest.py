"""
Shared pytest fixtures.

The server is restarted before every test, so there is deliberately no state-bearing
fixture here: the only session-scoped object is the HTTP client itself. Everything a test
needs in the store is built inside the test through the scenario builders in
`test_helpers.fixtures`, which go through the public endpoints like any other client.

Four of the five roles are opaque operator identities and get a header fixture each, plus
a second identity where a duty is segregated. The fifth, `AttendingPhysician`, is
entity-backed: its `X-User-ID` must be a real `Physician` id, so its headers are built
inside each test from the physician that test created, via
`fixtures.World.physician_headers` or `make_attending_physician_headers`.
"""

import pytest

from test_helpers import (
    ANALYST_2_HEADERS,
    ANALYST_3_HEADERS,
    ANALYST_HEADERS,
    INTAKE_2_HEADERS,
    INTAKE_HEADERS,
    NURSE_2_HEADERS,
    NURSE_HEADERS,
    OFFICER_2_HEADERS,
    OFFICER_HEADERS,
    api_client,
)


@pytest.fixture(scope="session")
def api():
    """The HTTP client, one method per declared operation."""
    return api_client


@pytest.fixture
def officer():
    """The compliance officer: reference data, recomputes, rescores and period close."""
    return OFFICER_HEADERS


@pytest.fixture
def second_officer():
    """A second compliance officer, for two-person scenarios."""
    return OFFICER_2_HEADERS


@pytest.fixture
def intake():
    """The intake coordinator: referral creation, screening and admission."""
    return INTAKE_HEADERS


@pytest.fixture
def second_intake():
    """A second intake coordinator."""
    return INTAKE_2_HEADERS


@pytest.fixture
def nurse():
    """The utilization review nurse: discharge, interruptions, notes and queries."""
    return NURSE_HEADERS


@pytest.fixture
def second_nurse():
    """A second nurse, who is the one allowed to close a query this one issued."""
    return NURSE_2_HEADERS


@pytest.fixture
def analyst():
    """The revenue integrity analyst who prices a stay."""
    return ANALYST_HEADERS


@pytest.fixture
def second_analyst():
    """A second analyst, who is the one allowed to finalize what the first priced."""
    return ANALYST_2_HEADERS


@pytest.fixture
def third_analyst():
    """A third analyst, who is the one allowed to void what the second finalized."""
    return ANALYST_3_HEADERS
