"""Pytest fixtures exposing the test_helpers infrastructure.

The runner restarts the server before every test, so no fixture here needs to
clean up: each test starts against an empty database with the logical clock at
its documented default of 2026-08-01T00:00:00Z (PRD §2.4).
"""
import pytest

from test_helpers import (
    ApiClient, api_client, make_admin_headers, make_employee_headers,
    make_employer_admin_headers, make_merchant_headers,
    make_partner_manager_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is the runner's business."""
    return api_client


@pytest.fixture
def admin_headers():
    """`PlatformAdmin` — an opaque identity (PRD §2.1)."""
    return make_admin_headers()


@pytest.fixture
def partner_manager_headers():
    """`PartnerManager` — an opaque identity (PRD §2.1)."""
    return make_partner_manager_headers()


@pytest.fixture
def merchant_headers_for():
    """Builder for entity-backed `Merchant` headers keyed on a merchant id."""
    return make_merchant_headers


@pytest.fixture
def employer_admin_headers_for():
    """Builder for entity-backed `EmployerAdmin` headers keyed on employer id."""
    return make_employer_admin_headers


@pytest.fixture
def employee_headers_for():
    """Builder for entity-backed `Employee` headers keyed on membership id."""
    return make_employee_headers
