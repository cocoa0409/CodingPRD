"""Shared pytest fixtures for the Preschool Child Find API contract suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.constants import INITIAL_LOGICAL_CLOCK  # noqa: E402
from test_helpers.factories import clock_payload  # noqa: E402
from test_helpers.test_users import TEST_USERS  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """One client for the whole session."""
    return ApiClient()


@pytest.fixture(autouse=True)
def logical_clock(api):
    """Pin the server's logical clock before every test.

    No rule in this system reads wall-clock time; every deadline, age, window and
    compliance figure reads the server's logical clock instead. Each test therefore
    starts from the documented initial instant unless it moves the clock itself.
    """
    api.set_clock(clock_payload(INITIAL_LOGICAL_CLOCK), TEST_USERS["district_admin_headers"])
    return INITIAL_LOGICAL_CLOCK


@pytest.fixture
def coordinator():
    """A ChildFindCoordinator's headers."""
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def placement():
    """A PlacementAdministrator's headers."""
    return TEST_USERS["placement_headers"]


@pytest.fixture
def district_admin():
    """A DistrictAdmin's headers."""
    return TEST_USERS["district_admin_headers"]


@pytest.fixture
def chair_headers():
    """EvaluationChair headers whose identity matches no provider row."""
    return TEST_USERS["chair_headers"]


@pytest.fixture
def evaluator_headers():
    """Evaluator headers whose identity matches no provider row."""
    return TEST_USERS["evaluator_headers"]


@pytest.fixture
def parent_headers():
    """Parent headers whose identity matches no child row."""
    return TEST_USERS["parent_headers"]
