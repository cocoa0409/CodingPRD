"""Pytest fixtures exposing the shared test_helpers infrastructure.

The runner relaunches the server and clears the database before every single
test, so no fixture here needs to clean up: every test starts from an empty
database with the logical clock at its declared default instant.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client
from test_helpers import make_installer_operator_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def manufacturer_admin_headers():
    return TEST_USERS["manufacturer_admin_headers"]


@pytest.fixture
def design_consultant_headers():
    return TEST_USERS["design_consultant_headers"]


@pytest.fixture
def design_consultant_2_headers():
    return TEST_USERS["design_consultant_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_2_headers():
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def client_representative_headers():
    return TEST_USERS["client_representative_headers"]


@pytest.fixture
def safety_auditor_headers():
    return TEST_USERS["safety_auditor_headers"]


@pytest.fixture
def safety_auditor_2_headers():
    return TEST_USERS["safety_auditor_2_headers"]


@pytest.fixture
def installer_operator_headers():
    """Fallback InstallerOperator identity.

    Only for calls that never reach a job-ownership comparison; ownership-gated
    calls must use make_installer_operator_headers(installer["id"]).
    """
    return TEST_USERS["installer_operator_headers"]


@pytest.fixture
def installer_headers_factory():
    """Builds InstallerOperator headers for a specific CertifiedInstaller id."""
    return make_installer_operator_headers
