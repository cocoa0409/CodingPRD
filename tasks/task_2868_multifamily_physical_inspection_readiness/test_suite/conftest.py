"""Shared pytest fixtures for the readiness API test suite."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The endpoint-per-method HTTP client."""
    return api_client


@pytest.fixture
def property_owner_headers():
    """A PropertyOwner identity that owns no property.

    Ownership-gated calls must build their headers from the property's own id
    with `make_property_owner_headers`; this entry exists only for the cases
    where reaching no property is the point.
    """
    return TEST_USERS["property_owner_headers"]


@pytest.fixture
def housing_agency_inspector_headers():
    return TEST_USERS["housing_agency_inspector_headers"]


@pytest.fixture
def maintenance_technician_headers():
    return TEST_USERS["maintenance_technician_headers"]


@pytest.fixture
def quality_assurance_reviewer_headers():
    return TEST_USERS["quality_assurance_reviewer_headers"]


@pytest.fixture
def quality_assurance_reviewer_alt_headers():
    """A second, distinct QualityAssuranceReviewer identity."""
    return TEST_USERS["quality_assurance_reviewer_alt_headers"]


@pytest.fixture
def appeals_officer_headers():
    return TEST_USERS["appeals_officer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
