"""Shared pytest fixtures.

The harness restarts the server before every test, so no fixture may assume any
state survives from an earlier test.
"""

import pytest

from test_helpers.api_client import api_client
from test_helpers.test_users import (
    make_compliance_headers,
    make_coordinator_headers,
    make_director_headers,
    make_guest_headers,
    make_therapist_headers,
)


@pytest.fixture(scope="session")
def api():
    """The API client, one instance for the whole session."""
    return api_client


@pytest.fixture
def director_headers():
    """SpaDirector — the only role that may move the logical clock (PRD §2.4)."""
    return make_director_headers()


@pytest.fixture
def compliance_headers():
    return make_compliance_headers()


@pytest.fixture
def coordinator_headers():
    return make_coordinator_headers()


@pytest.fixture
def therapist_headers_for():
    """Therapist headers are entity-backed: pass the real Therapist.id."""
    return make_therapist_headers


@pytest.fixture
def guest_headers_for():
    """Guest headers are entity-backed: pass the real Guest.id."""
    return make_guest_headers
