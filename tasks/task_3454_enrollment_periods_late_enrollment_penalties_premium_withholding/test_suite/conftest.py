"""Pytest fixture bridge: exposes the test_helpers surface to the suite.

The runner owns server lifecycle, API_BASE_URL injection and PYTHONPATH;
this module only re-registers the client fixtures defined in
``test_helpers.fixtures`` and adds one header fixture per declared role.
Ownership-gated calls must still build per-beneficiary headers with
``make_beneficiary_headers`` at call time (see test_helpers.test_users).
"""

import pytest

from test_helpers import TEST_USERS
from test_helpers.fixtures import api, client  # noqa: F401  (re-registered)


@pytest.fixture
def beneficiary_headers():
    """Fallback Beneficiary headers for calls that are not ownership-gated."""
    return TEST_USERS["beneficiary_headers"]


@pytest.fixture
def field_officer_headers():
    return TEST_USERS["field_officer_headers"]


@pytest.fixture
def appeals_officer_headers():
    return TEST_USERS["appeals_officer_headers"]


@pytest.fixture
def irs_data_agent_headers():
    return TEST_USERS["irs_data_agent_headers"]


@pytest.fixture
def benefit_administrator_headers():
    return TEST_USERS["benefit_administrator_headers"]
