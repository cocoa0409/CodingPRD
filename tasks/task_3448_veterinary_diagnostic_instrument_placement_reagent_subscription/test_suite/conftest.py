"""Pytest fixtures exposing the test_helpers infrastructure (PRD §2).

The server lifecycle is managed by the external runner; tests assume the
API is reachable and the database is empty at the start of every test.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped shared API client (server lifecycle managed externally)."""
    return api_client


@pytest.fixture
def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def finance_reviewer_headers() -> dict:
    return TEST_USERS["finance_reviewer_headers"]


@pytest.fixture
def clinic_manager_headers() -> dict:
    """Shared ClinicManager headers. Fallback only: this identity matches no
    clinic, so ownership-gated calls must build per-clinic headers instead."""
    return TEST_USERS["clinic_manager_headers"]


@pytest.fixture
def field_service_engineer_headers() -> dict:
    return TEST_USERS["field_service_engineer_headers"]


@pytest.fixture
def laboratory_technician_headers() -> dict:
    return TEST_USERS["laboratory_technician_headers"]
