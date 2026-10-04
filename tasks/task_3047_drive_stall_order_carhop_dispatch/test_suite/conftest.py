"""Pytest fixtures exposing test_helpers infrastructure."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def shift_manager_headers():
    return TEST_USERS["shift_manager_headers"]


@pytest.fixture
def kitchen_staff_headers():
    return TEST_USERS["kitchen_staff_headers"]


@pytest.fixture
def carhop_headers():
    return TEST_USERS["carhop_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
