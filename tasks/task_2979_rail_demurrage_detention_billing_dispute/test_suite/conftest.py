"""Pytest fixtures exposing the ``test_helpers`` infrastructure.

The runner owns the server lifecycle, ``API_BASE_URL`` and ``PYTHONPATH``, and it
relaunches the service before every individual test - so each test starts from an
empty database with the logical clock at its cold-start value of
``2026-08-01T00:00:00Z`` (PRD 2.4).  Nothing here needs to reset state.
"""

import pytest

from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    ADMIN,
    ADMIN_USER_ID,
    AGENT,
    AGENT_USER_ID,
    OFFICER,
    OFFICER_USER_ID,
    make_adjudicator_headers,
)


@pytest.fixture()
def api() -> ApiClient:
    """A client pointed at the service under test."""
    return ApiClient()


@pytest.fixture()
def agent_headers():
    """PRD 2.1 - the RailroadAgent role."""
    return AGENT


@pytest.fixture()
def officer_headers():
    """PRD 2.1 - the RegulatoryOfficer role."""
    return OFFICER


@pytest.fixture()
def admin_headers():
    """PRD 2.1 - the BillingAdmin role."""
    return ADMIN


@pytest.fixture()
def adjudicator_headers():
    """PRD 2.1 - a DemurrageAdjudicator with a stable, distinguishable identity."""
    return make_adjudicator_headers("adj-primary")


@pytest.fixture()
def second_adjudicator_headers():
    """A second, genuinely different adjudicator.

    PRD 3.8 bars the holder of ``first_level_adjudicator_id`` from taking the
    appeal, so the two identities must be distinct persisted values.
    """
    return make_adjudicator_headers("adj-secondary")


@pytest.fixture()
def user_ids():
    return {
        "agent": AGENT_USER_ID,
        "officer": OFFICER_USER_ID,
        "admin": ADMIN_USER_ID,
    }
