"""Shared pytest fixtures for the shell-egg operations API suite.

The harness restarts the server before every test, so each test starts from
an empty database and builds every precondition it needs through the API
itself.  PRD §2.4 gives the server a logical clock whose startup value is
exactly ``2026-09-01T00:00:00Z``; composite helpers in ``test_helpers`` pin
the clock explicitly whenever a recipe requires it.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    make_complex_manager_headers,
    make_customer_headers,
)


@pytest.fixture(scope="session")
def api():
    """The API client, one method per endpoint the PRD defines."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    """PRD §2.1: the platform operator (configuration, quotations, clock)."""
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def production_planner_headers():
    """PRD §2.1: plans flock placements and conversions; runs allocation."""
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def plant_manager_headers():
    """PRD §2.1: runs grading/packing and ships orders (opaque identity)."""
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def procurement_lead_headers():
    """PRD §2.1: buys corn and soybean meal and manages hedges."""
    return TEST_USERS["procurement_lead_headers"]


@pytest.fixture
def health_official_headers():
    """PRD §2.1: veterinary authority for disease events and depopulation."""
    return TEST_USERS["health_official_headers"]


@pytest.fixture
def quality_auditor_headers():
    """PRD §2.1: third-party auditor for specialty-program certifications."""
    return TEST_USERS["quality_auditor_headers"]


@pytest.fixture
def sales_manager_headers():
    """PRD §2.1: owns customer commitments and the settlement lifecycle."""
    return TEST_USERS["sales_manager_headers"]


@pytest.fixture
def customer_headers_for():
    """Build ``Customer`` headers for a customer id (entity-backed, PRD §2.1)."""
    return make_customer_headers


@pytest.fixture
def complex_manager_headers_for():
    """Build ``ComplexManager`` headers for a complex id (entity-backed)."""
    return make_complex_manager_headers
