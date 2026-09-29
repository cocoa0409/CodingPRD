"""Shared pytest fixtures for the structured-cabling contracting suite.

The harness restarts the server before each test, so every test begins against an
empty store and builds all of its preconditions through the declared endpoints.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: F401,E402  registers the status map
from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.constants import CLOCK_EPOCH  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    CERTIFIER_HEADERS,
    CLIENT_HEADERS,
    DESIGNER_HEADERS,
    INSTALLER_HEADERS,
    MANUFACTURER_HEADERS,
    PM_HEADERS,
    TESTER_HEADERS,
)


@pytest.fixture
def client() -> ApiClient:
    """A client pointed at the server under test."""
    return ApiClient()


@pytest.fixture
def pm_headers():
    return PM_HEADERS


@pytest.fixture
def designer_headers():
    return DESIGNER_HEADERS


@pytest.fixture
def installer_headers():
    return INSTALLER_HEADERS


@pytest.fixture
def tester_headers():
    return TESTER_HEADERS


@pytest.fixture
def certifier_headers():
    return CERTIFIER_HEADERS


@pytest.fixture
def manufacturer_headers():
    return MANUFACTURER_HEADERS


@pytest.fixture
def client_headers():
    return CLIENT_HEADERS


@pytest.fixture
def clock_epoch() -> str:
    """The instant the logical site clock starts at."""
    return CLOCK_EPOCH
