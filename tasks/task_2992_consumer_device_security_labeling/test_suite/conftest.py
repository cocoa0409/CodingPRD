"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle and restarts it before every test, so each
test observes an empty database and a logical clock parked at its initial value.
"""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    fixtures,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# --------------------------------------------------------------------------
# Role headers
# --------------------------------------------------------------------------
@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_2_headers():
    return TEST_USERS["admin_2_headers"]


@pytest.fixture
def admin_notice_headers():
    return TEST_USERS["admin_notice_headers"]


@pytest.fixture
def admin_adjudicate_headers():
    return TEST_USERS["admin_adjudicate_headers"]


@pytest.fixture
def admin_vacate_headers():
    return TEST_USERS["admin_vacate_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def reviewer_2_headers():
    return TEST_USERS["reviewer_2_headers"]


@pytest.fixture
def consumer_headers():
    return TEST_USERS["consumer_headers"]


@pytest.fixture
def manufacturer_headers():
    return TEST_USERS["manufacturer_headers"]


@pytest.fixture
def test_lab_operator_headers():
    return TEST_USERS["test_lab_operator_headers"]


@pytest.fixture
def retailer_headers():
    return TEST_USERS["retailer_headers"]


# --------------------------------------------------------------------------
# Composite setup
# --------------------------------------------------------------------------
@pytest.fixture
def program():
    """Self-attestation tier, one eligible category, five-criterion catalogue."""
    return fixtures.create_program("SELF_ATTESTATION")


@pytest.fixture
def third_party_program():
    """Third-party-test tier, one eligible category, five-criterion catalogue."""
    return fixtures.create_program("THIRD_PARTY_TEST")


@pytest.fixture
def sponsor():
    return fixtures.enrol_manufacturer()


@pytest.fixture
def large_sponsor():
    return fixtures.enrol_large_manufacturer()


@pytest.fixture
def lab():
    return fixtures.register_lab()


@pytest.fixture
def store():
    """A retailer that has already acknowledged the education materials."""
    return fixtures.register_retailer()
