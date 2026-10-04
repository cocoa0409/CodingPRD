"""Pytest wiring: exposes the API client and role headers as fixtures.

The runner restarts the API server before every test and injects
``API_BASE_URL`` into the environment, so the client is constructed with no
arguments and every test builds its own world from an empty database.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS


@pytest.fixture()
def api() -> ApiClient:
    return ApiClient()


@pytest.fixture()
def program_ops_headers():
    return TEST_USERS["program_ops"]


@pytest.fixture()
def sponsor_bank_ops_headers():
    return TEST_USERS["sponsor_bank_ops"]


@pytest.fixture()
def disputes_agent_headers():
    return TEST_USERS["disputes_agent"]


@pytest.fixture()
def member_headers():
    return TEST_USERS["member"]
