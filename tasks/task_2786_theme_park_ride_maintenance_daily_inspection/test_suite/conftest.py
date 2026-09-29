"""Shared pytest fixtures for the ride maintenance and daily inspection suite.

The runner owns the server lifecycle and hands every test a freshly started
process, so each test begins against an empty database with the logical clock at
its declared start instant. Preconditions are therefore always built through the
declared endpoints rather than seeded directly.
"""

import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The shared HTTP client bound to the runner-supplied base URL."""
    return api_client


@pytest.fixture
def park_ops_admin_headers():
    return TEST_USERS["park_ops_admin_headers"]


@pytest.fixture
def maintenance_manager_headers():
    return TEST_USERS["maintenance_manager_headers"]


@pytest.fixture
def maintenance_technician_headers():
    return TEST_USERS["maintenance_technician_headers"]


@pytest.fixture
def qualified_inspector_headers():
    return TEST_USERS["qualified_inspector_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def ride_operator_headers():
    return TEST_USERS["ride_operator_headers"]
