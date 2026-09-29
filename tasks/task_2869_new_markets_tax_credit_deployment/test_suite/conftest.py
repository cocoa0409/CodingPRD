"""Pytest fixtures exposing the NMTC test infrastructure.

The server lifecycle, base URL and import path are the runner's concern; these
fixtures only hand tests a client and pre-built identity headers.
"""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def agency_headers() -> dict:
    """The federal certifying and allocating authority."""
    return TEST_USERS["agency_headers"]


@pytest.fixture
def cde_sponsor_headers() -> dict:
    """A community development entity identity that owns nothing.

    Use only where no ownership check is reached; otherwise build headers from
    the acting entity's own id.
    """
    return TEST_USERS["cde_sponsor_headers"]


@pytest.fixture
def investor_headers() -> dict:
    """The tax-credit investor that capitalises the fund and holds the put."""
    return TEST_USERS["investor_headers"]


@pytest.fixture
def qalicb_sponsor_headers() -> dict:
    """The sponsor of the project company."""
    return TEST_USERS["qalicb_sponsor_headers"]


@pytest.fixture
def eligibility_reviewer_headers() -> dict:
    """The compliance reviewer that runs project-company eligibility tests."""
    return TEST_USERS["eligibility_reviewer_headers"]


@pytest.fixture
def annual_reviewer_headers() -> dict:
    """The second compliance reviewer, free to run the annual compliance test."""
    return TEST_USERS["annual_reviewer_headers"]


@pytest.fixture
def cba_reviewer_headers() -> dict:
    """A third compliance reviewer identity, for community-benefits work."""
    return TEST_USERS["cba_reviewer_headers"]
