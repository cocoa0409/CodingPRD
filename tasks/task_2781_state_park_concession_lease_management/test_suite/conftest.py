"""Shared pytest fixtures for the compliance suite."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers import test_users  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return ApiClient(os.environ.get("API_BASE_URL"))


@pytest.fixture
def admin(api):
    return test_users.admin_headers()


@pytest.fixture
def specialist(api):
    return test_users.specialist_headers()


@pytest.fixture
def award_officer(api):
    return test_users.award_officer_headers()


@pytest.fixture
def exec_officer(api):
    return test_users.exec_officer_headers()


@pytest.fixture
def panelist(api):
    return test_users.panelist_headers()


@pytest.fixture
def auditor(api):
    return test_users.auditor_headers()
