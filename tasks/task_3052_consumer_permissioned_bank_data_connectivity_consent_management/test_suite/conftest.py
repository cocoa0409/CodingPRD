"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the API server before each test and injects the base URL
into the environment, so the client is constructed with no arguments and each
test builds its world from scratch through the public API.
"""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    make_admin_headers,
    make_consumer_headers,
    make_recipient_headers,
    make_reviewer_headers,
)


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def admin_headers():
    return make_admin_headers()


@pytest.fixture()
def reviewer_headers():
    return make_reviewer_headers()
