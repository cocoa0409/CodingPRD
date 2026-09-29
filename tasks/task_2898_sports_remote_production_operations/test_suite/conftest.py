"""Shared pytest fixtures for the Broadcast Operations API suite.

Importing ``test_helpers`` registers the error-id to HTTP-status map, so every
``validate_error`` call also checks the status code the PRD declares.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS


@pytest.fixture()
def api():
    """A client bound to the running server (base URL comes from the harness)."""
    return ApiClient()


@pytest.fixture()
def pm_headers():
    """ProductionManager identity headers."""
    return TEST_USERS["production_manager_headers"]


@pytest.fixture()
def pm_alt_headers():
    """A second, distinct ProductionManager operator identity."""
    return TEST_USERS["production_manager_alt_headers"]


@pytest.fixture()
def td_headers():
    """TechnicalDirector identity headers."""
    return TEST_USERS["technical_director_headers"]


@pytest.fixture()
def td_alt_headers():
    """A second, distinct TechnicalDirector operator identity."""
    return TEST_USERS["technical_director_alt_headers"]


@pytest.fixture()
def lo_headers():
    """LeagueOperations identity headers."""
    return TEST_USERS["league_operations_headers"]


@pytest.fixture()
def us_headers():
    """UnionSteward identity headers."""
    return TEST_USERS["union_steward_headers"]
