"""Shared pytest fixtures for the Electronic Resource Licensing test suite.

The harness restarts the server before every test, so every test starts from an
empty database and the logical clock sitting at its unset value.  Nothing here
persists state between tests.
"""

import pytest

from test_helpers import (
    api_client,
    make_admin_headers,
    make_engineer_headers,
    make_negotiator_headers,
    TEST_USERS,
)


@pytest.fixture(scope="session")
def api():
    """The API client for the platform under test."""
    return api_client


@pytest.fixture
def admin():
    """The collections-office operator. An opaque identity."""
    return make_admin_headers("admin-1")


@pytest.fixture
def second_admin():
    """A second, distinct collections-office operator."""
    return make_admin_headers("admin-2")


@pytest.fixture
def negotiator():
    """A licence negotiator. An opaque identity."""
    return make_negotiator_headers("neg-1")


@pytest.fixture
def second_negotiator():
    """A second, distinct licence negotiator."""
    return make_negotiator_headers("neg-2")


@pytest.fixture
def engineer():
    """An access services engineer. An opaque identity."""
    return make_engineer_headers("eng-1")


@pytest.fixture
def librarian():
    """A member librarian whose identity names no stored member library.

    Use only where no ownership check applies: role rejections, missing-resource
    lookups and shape rejections.  Anywhere ownership matters, build the headers
    from the real member id instead.
    """
    return dict(TEST_USERS["librarian_headers"])


@pytest.fixture
def vendor_rep():
    """A vendor representative whose identity names no stored vendor.

    Same caveat as ``librarian``: only for surfaces that never reach an
    ownership comparison.
    """
    return dict(TEST_USERS["vendor_rep_headers"])
