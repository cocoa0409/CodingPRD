"""Pytest bridge between the shared test helpers and the test modules."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_client as _api_client  # noqa: E402
from test_helpers import TEST_USERS  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """The domain API client, shared for the whole session."""
    return _api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def permit_coordinator_headers():
    return TEST_USERS["permit_coordinator_headers"]


@pytest.fixture
def dispatch_planner_headers():
    return TEST_USERS["dispatch_planner_headers"]


@pytest.fixture
def driver_operator_headers():
    return TEST_USERS["driver_operator_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def second_compliance_officer_headers():
    return TEST_USERS["second_compliance_officer_headers"]


@pytest.fixture
def customer_contact_headers():
    return TEST_USERS["customer_contact_headers"]
