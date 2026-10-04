"""Pytest fixtures exposing the test_helpers infrastructure.

The runner (prd-bench-local-runner) sets ``API_BASE_URL`` in the pytest
subprocess environment and restarts the API server on the same base URL
before every test (``--isolation per-test-server``), so the module-level
``api_client`` singleton — which reads ``API_BASE_URL`` at construction — is
correct for the whole session.
"""
import pytest

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    INSPECTOR_HEADERS,
    OWNER_REPRESENTATIVE_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    PROJECT_ENGINEER_HEADERS,
    TECHNICAL_SERVICE_ENGINEER_HEADERS,
    ApiClient,
    api_client,
    make_applicator_rep_headers,
    make_inspector_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return PLATFORM_ADMIN_HEADERS


@pytest.fixture
def technical_service_engineer_headers():
    return TECHNICAL_SERVICE_ENGINEER_HEADERS


@pytest.fixture
def project_engineer_headers():
    return PROJECT_ENGINEER_HEADERS


@pytest.fixture
def owner_representative_headers():
    return OWNER_REPRESENTATIVE_HEADERS


@pytest.fixture
def inspector_headers():
    return INSPECTOR_HEADERS


@pytest.fixture
def compliance_officer_headers():
    return COMPLIANCE_OFFICER_HEADERS


@pytest.fixture
def applicator_rep_headers_factory():
    """Builder for the entity-backed ApplicatorRep role: pass the Applicator id."""
    return make_applicator_rep_headers


@pytest.fixture
def inspector_headers_factory():
    """Builder for an Inspector identity distinct from any applicator id."""
    return make_inspector_headers
