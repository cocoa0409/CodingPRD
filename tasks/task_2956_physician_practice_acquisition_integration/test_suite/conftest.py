"""Shared pytest fixtures for the Practice Acquisition Integration suite.

The harness owns the server lifecycle and exports `API_BASE_URL`, so the client
fixture only has to construct the client. Each test runs against a freshly
started server with an empty store, so no cleanup is performed here.
"""

import pytest

from test_helpers.api_client import ApiClient
from test_helpers.fixtures import (  # noqa: F401  (re-exported as pytest fixtures)
    acquisition,
    board_review_fixture,
    clock_at_default,
    closed_fixture,
    diligence_fixture,
    signed_fixture,
)
from test_helpers.test_users import (
    make_compensation_designer_headers,
    make_compliance_officer_headers,
    make_deal_lead_headers,
    make_integration_manager_headers,
    make_valuation_analyst_headers,
)
from test_helpers.constants import (
    USER_COMPLIANCE_OFFICER_ALT,
    USER_VALUATION_ANALYST_ALT,
)


@pytest.fixture
def api() -> ApiClient:
    """Client bound to the base URL the harness exports."""
    return ApiClient()


@pytest.fixture
def deal_lead_headers():
    return make_deal_lead_headers()


@pytest.fixture
def valuation_analyst_headers():
    return make_valuation_analyst_headers()


@pytest.fixture
def second_analyst_headers():
    """A second `ValuationAnalyst` identity, distinct from the first."""
    return make_valuation_analyst_headers(USER_VALUATION_ANALYST_ALT)


@pytest.fixture
def compliance_officer_headers():
    return make_compliance_officer_headers()


@pytest.fixture
def second_officer_headers():
    """A second `ComplianceOfficer` identity, distinct from the first."""
    return make_compliance_officer_headers(USER_COMPLIANCE_OFFICER_ALT)


@pytest.fixture
def compensation_designer_headers():
    return make_compensation_designer_headers()


@pytest.fixture
def integration_manager_headers():
    return make_integration_manager_headers()
