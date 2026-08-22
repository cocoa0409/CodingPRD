"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def contract_admin_headers():
    return TEST_USERS["contract_admin_headers"]


@pytest.fixture
def second_contract_admin_headers():
    return TEST_USERS["second_contract_admin_headers"]


@pytest.fixture
def materials_manager_headers():
    return TEST_USERS["materials_manager_headers"]


@pytest.fixture
def clinician_headers():
    return TEST_USERS["clinician_headers"]


@pytest.fixture
def second_clinician_headers():
    return TEST_USERS["second_clinician_headers"]


@pytest.fixture
def distribution_operator_headers():
    return TEST_USERS["distribution_operator_headers"]


@pytest.fixture
def second_distribution_operator_headers():
    return TEST_USERS["second_distribution_operator_headers"]


@pytest.fixture
def manufacturer_rep_headers():
    return TEST_USERS["manufacturer_rep_headers"]
