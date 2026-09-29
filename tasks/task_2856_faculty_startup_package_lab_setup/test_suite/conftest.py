"""Shared pytest fixtures.

The server is restarted before every test, so each test observes an empty
database and builds every precondition it needs through the public API.
"""

import pytest

from test_helpers import api_client
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.test_users import (
    make_dean_office_headers,
    make_facilities_manager_headers,
)


@pytest.fixture
def api():
    """The API client used by every test."""
    return api_client


@pytest.fixture
def dean_office_headers():
    """DeanOffice acts on an opaque staff identity, not on a stored entity."""
    return make_dean_office_headers(TEST_DEFAULTS["DEAN_OFFICE_USER_ID"])


@pytest.fixture
def facilities_headers():
    """FacilitiesManager also acts on an opaque staff identity."""
    return make_facilities_manager_headers(TEST_DEFAULTS["FACILITIES_USER_ID"])
