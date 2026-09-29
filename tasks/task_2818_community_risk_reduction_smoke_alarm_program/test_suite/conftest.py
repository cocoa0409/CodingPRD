"""Pytest fixture bridge exposing the test_helpers infrastructure.

The composite setup helpers live in ``test_helpers.fixtures``; importing their
fixture functions here makes them available to every test module.
"""

import pytest

from test_helpers import TEST_USERS
from test_helpers.constants import Role
from test_helpers.fixtures import (  # noqa: F401  (pytest fixtures)
    api,
    assessed_zone,
    canvass_context,
    committed_installation_context,
    crew,
    funded_visit_context,
    pinned_clock,
    scheduled_visit_context,
    serviced_household_context,
)


@pytest.fixture
def program_admin_headers():
    return TEST_USERS[Role.PROGRAM_ADMIN]


@pytest.fixture
def risk_analyst_headers():
    return TEST_USERS[Role.RISK_ANALYST]


@pytest.fixture
def canvass_coordinator_headers():
    return TEST_USERS[Role.CANVASS_COORDINATOR]


@pytest.fixture
def grant_officer_headers():
    return TEST_USERS[Role.GRANT_OFFICER]
