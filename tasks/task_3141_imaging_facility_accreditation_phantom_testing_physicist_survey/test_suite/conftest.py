"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle, `API_BASE_URL` and `PYTHONPATH`; this file
only wires the generated helpers into pytest fixtures.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def facility_admin_headers():
    return TEST_USERS["facility_admin_headers"]


@pytest.fixture
def medical_physicist_headers():
    return TEST_USERS["medical_physicist_headers"]


@pytest.fixture
def accreditation_body_headers():
    return TEST_USERS["accreditation_body_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]