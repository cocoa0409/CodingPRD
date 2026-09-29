"""Pytest fixtures exposing the program test infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def decon_technician_headers():
    return TEST_USERS["decon_technician_headers"]


@pytest.fixture
def release_verifier_headers():
    return TEST_USERS["release_verifier_headers"]


@pytest.fixture
def enforcement_officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def state_data_steward_headers():
    return TEST_USERS["state_data_steward_headers"]


@pytest.fixture
def training_officer_headers():
    return TEST_USERS["training_officer_headers"]
