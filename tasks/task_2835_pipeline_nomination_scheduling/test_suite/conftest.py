"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def shipper_headers():
    return TEST_USERS["shipper_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def terminal_operator_headers():
    return TEST_USERS["terminal_operator_headers"]


@pytest.fixture
def tariff_administrator_headers():
    return TEST_USERS["tariff_administrator_headers"]


@pytest.fixture
def publisher_headers():
    return TEST_USERS["publisher_headers"]


@pytest.fixture
def certifier_headers():
    return TEST_USERS["certifier_headers"]


@pytest.fixture
def second_certifier_headers():
    return TEST_USERS["second_certifier_headers"]


@pytest.fixture
def invoicer_headers():
    return TEST_USERS["invoicer_headers"]
