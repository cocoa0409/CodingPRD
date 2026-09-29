"""Shared pytest fixtures for the pop-up experience operations suite.

The harness relaunches the service before every test, so each test starts
against an empty database with the logical clock on its declared starting
instant of 2026-08-01T00:00:00Z.  Nothing here writes to the database.
"""

import pytest

from test_helpers import TEST_USERS, api_client, make_guest_headers


@pytest.fixture(scope="session")
def api():
    """The endpoint client, shared for the whole session."""
    return api_client


@pytest.fixture
def venue_ops_manager_headers():
    """Headers for the operator who registers venues and draws buildout money."""
    return TEST_USERS["venue_ops_manager_headers"]


@pytest.fixture
def licensing_manager_headers():
    """Headers for the operator who registers licences and cuts statements."""
    return TEST_USERS["licensing_manager_headers"]


@pytest.fixture
def licensor_rep_headers():
    """Headers for the licensor's representative of record."""
    return TEST_USERS["licensor_rep_headers"]


@pytest.fixture
def other_licensor_rep_headers():
    """Headers for a licensor representative who is not the one of record."""
    return TEST_USERS["other_licensor_rep_headers"]


@pytest.fixture
def experience_producer_headers():
    """Headers for the producer who designs and runs the installation."""
    return TEST_USERS["experience_producer_headers"]


@pytest.fixture
def other_experience_producer_headers():
    """Headers for a second producer, needed wherever duties are segregated."""
    return TEST_USERS["other_experience_producer_headers"]


@pytest.fixture
def safety_officer_headers():
    """Headers for the officer who records permits and inspections."""
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def other_safety_officer_headers():
    """Headers for a second officer, needed to lift a suspension."""
    return TEST_USERS["other_safety_officer_headers"]


@pytest.fixture
def guest_services_agent_headers():
    """Headers for the agent who opens guest accounts and sells tickets."""
    return TEST_USERS["guest_services_agent_headers"]


@pytest.fixture
def guest_headers():
    """A builder for Guest headers.

    Guest is the one entity-backed role: the acting user identifier is the id
    of the acting guest account, so the headers can only be built once a real
    account exists.
    """
    return make_guest_headers
