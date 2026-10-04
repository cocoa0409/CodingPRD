"""Pytest wiring for the Product Certification Followup suite.

The runner restarts the API server before every test and injects
``API_BASE_URL`` into the environment, so each test starts against an empty
database and builds the world it needs through ``test_helpers.fixtures``.
This module only bridges the helpers into pytest fixtures.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """API client aimed at the server under test.

    Constructed on first use, after the runner has injected API_BASE_URL;
    the runner owns the server lifecycle.
    """
    return ApiClient()


# One header-set fixture per opaque role. The two entity-backed roles
# (ManufacturerRep, AHJAuthority) intentionally have no fixture: their headers
# must be built per test from the created entity's id via
# test_helpers.make_manufacturer_rep_headers / make_ahj_authority_headers.


@pytest.fixture
def admin_headers():
    return TEST_USERS["certification_body_admin_headers"]


@pytest.fixture
def engineer_headers():
    return TEST_USERS["test_engineer_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["certification_reviewer_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["factory_inspector_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["compliance_officer_headers"]
