"""Shared pytest fixtures for the suite."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_helpers import TEST_USERS, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """The API client every test drives the server through."""
    return api_client


@pytest.fixture
def producer_headers():
    return TEST_USERS["show_producer_headers"]


@pytest.fixture
def merchandiser_headers():
    return TEST_USERS["merchandising_manager_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def cert_officer_headers():
    return TEST_USERS["compliance_officer_cert_headers"]


@pytest.fixture
def signoff_officer_headers():
    return TEST_USERS["compliance_officer_signoff_headers"]


@pytest.fixture
def moderator_headers():
    return TEST_USERS["moderator_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def host_headers():
    return TEST_USERS["host_headers"]


@pytest.fixture
def viewer_headers():
    return TEST_USERS["viewer_headers"]
