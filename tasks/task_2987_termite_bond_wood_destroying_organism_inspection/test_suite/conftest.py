"""Shared pytest fixtures bridging the test helpers into the test suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADJUDICATOR_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
)


@pytest.fixture(scope="session")
def api():
    """The HTTP client under test."""
    return ApiClient()


@pytest.fixture
def officer():
    """Headers for a ComplianceOfficer, whose identifier is opaque."""
    return OFFICER_HEADERS


@pytest.fixture
def manager():
    """Headers for a BranchManager, whose identifier is opaque."""
    return MANAGER_HEADERS


@pytest.fixture
def adjudicator():
    """Headers for a ClaimsAdjudicator, whose identifier is opaque."""
    return ADJUDICATOR_HEADERS
