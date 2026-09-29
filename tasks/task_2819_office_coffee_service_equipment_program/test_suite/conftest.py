"""Shared fixtures for the generated suite.

The harness restarts the service and empties its store before every single
test, so nothing here caches state across tests: each fixture is function
scoped and every precondition is rebuilt from scratch through the declared
endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    TEST_USERS,
    make_customer_contact_headers,
    make_route_technician_headers,
)


@pytest.fixture
def api():
    """A thin client bound to the service under test."""
    return ApiClient()


@pytest.fixture
def program_admin():
    """Headers for the operator who owns routes, catalog and global capabilities."""
    return dict(TEST_USERS["program_admin_headers"])


@pytest.fixture
def account_manager():
    """Headers for the operator who owns accounts, sites, placements and visits."""
    return dict(TEST_USERS["account_manager_headers"])


@pytest.fixture
def billing_specialist():
    """Headers for the operator who owns invoicing, compliance and repricing."""
    return dict(TEST_USERS["billing_specialist_headers"])


@pytest.fixture
def route_technician_headers():
    """Builder for a technician identity that resolves to one route."""
    return make_route_technician_headers


@pytest.fixture
def customer_contact_headers():
    """Builder for a contact identity that resolves to one account."""
    return make_customer_contact_headers
