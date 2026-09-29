"""Pytest fixtures exposing the ``test_helpers`` infrastructure.

The runner restarts the API server before every test and puts the task root on
``PYTHONPATH``, so each test gets a fresh database and can import
``test_helpers`` directly.  Per PRD S2.5 a freshly started server reports a
logical compliance clock of ``2026-08-01T00:00:00.000Z``; tests that care about
time move it explicitly.

Only the three opaque staff roles get header fixtures.  ``CarrierRep`` and
``InsuranceFiler`` are entity-backed (S2.1), so their headers must be built
from the id of the row created inside the test.
"""

import pytest

from test_helpers import (
    ApiClient,
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_ALT,
    REGISTRY_ADMIN,
    VETTING_ANALYST,
    VETTING_ANALYST_ALT,
)


@pytest.fixture
def api() -> ApiClient:
    """API client for the server the runner started for this test."""
    return ApiClient()


@pytest.fixture
def registry_admin_headers():
    return REGISTRY_ADMIN


@pytest.fixture
def vetting_analyst_headers():
    return VETTING_ANALYST


@pytest.fixture
def vetting_analyst_alt_headers():
    return VETTING_ANALYST_ALT


@pytest.fixture
def compliance_officer_headers():
    return COMPLIANCE_OFFICER


@pytest.fixture
def compliance_officer_alt_headers():
    return COMPLIANCE_OFFICER_ALT
