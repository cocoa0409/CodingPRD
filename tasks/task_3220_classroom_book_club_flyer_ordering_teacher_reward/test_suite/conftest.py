"""Shared pytest wiring for the Classroom Book Club suite.

The harness restarts the API server before each test, so every test starts
against an empty database and builds the world it needs through the public
API. The base URL is injected into the environment by the runner, so the
client is constructed with no arguments.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def club_admin_headers():
    return TEST_USERS["club_admin_headers"]


@pytest.fixture()
def school_admin_headers():
    return TEST_USERS["school_admin_headers"]


@pytest.fixture()
def teacher_headers():
    return TEST_USERS["teacher_headers"]


@pytest.fixture()
def parent_headers():
    return TEST_USERS["parent_headers"]


@pytest.fixture()
def donor_headers():
    return TEST_USERS["donor_headers"]
