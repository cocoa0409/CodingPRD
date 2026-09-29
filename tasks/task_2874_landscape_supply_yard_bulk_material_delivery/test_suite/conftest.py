"""Shared fixtures for the Landscape Supply Yard API suite."""

from __future__ import annotations

import pytest

from test_helpers import api_client
from test_helpers.test_users import TEST_USERS


@pytest.fixture(scope="session")
def api():
    """The HTTP client bound to the API base URL the harness injected."""
    return api_client


@pytest.fixture
def yard_admin():
    return TEST_USERS["yard_admin"]


@pytest.fixture
def credit_manager():
    return TEST_USERS["credit_manager"]


@pytest.fixture
def dispatch_planner():
    return TEST_USERS["dispatch_planner"]


@pytest.fixture
def yard_loader():
    return TEST_USERS["yard_loader"]


@pytest.fixture
def claims_adjuster():
    return TEST_USERS["claims_adjuster"]


@pytest.fixture
def contractor():
    return TEST_USERS["contractor"]
