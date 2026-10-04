"""Pytest fixtures exposing test_helpers infrastructure.

The harness restarts the API server before each test, so every test starts
against an empty database and builds the world it needs through the public
API. The base URL is injected by the runner, so the client takes no arguments.
"""

import pytest

from test_helpers import (
    ALLOCATION_OFFICER_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    DONOR_REPORTING_OFFICER_HEADERS,
    EMERGENCY_MANAGER_HEADERS,
    LOGISTICS_COORDINATOR_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    QA_PHARMACIST_HEADERS,
    ApiClient,
)


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def platform_admin_headers():
    return PLATFORM_ADMIN_HEADERS


@pytest.fixture()
def qa_pharmacist_headers():
    return QA_PHARMACIST_HEADERS


@pytest.fixture()
def compliance_officer_headers():
    return COMPLIANCE_OFFICER_HEADERS


@pytest.fixture()
def allocation_officer_headers():
    return ALLOCATION_OFFICER_HEADERS


@pytest.fixture()
def logistics_coordinator_headers():
    return LOGISTICS_COORDINATOR_HEADERS


@pytest.fixture()
def emergency_manager_headers():
    return EMERGENCY_MANAGER_HEADERS


@pytest.fixture()
def donor_reporting_officer_headers():
    return DONOR_REPORTING_OFFICER_HEADERS
