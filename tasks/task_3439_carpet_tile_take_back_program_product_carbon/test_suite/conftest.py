"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH: the API under test is already
running at API_BASE_URL, and test_helpers is importable without sys.path
hacks. The server is restarted before every test, so each test starts against
an empty database with the logical clock at 2026-09-01T00:00:00Z (PRD §2.5).
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    """PlatformAdmin headers (shared identity; not ownership-gated)."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def manager_headers() -> dict:
    """SustainabilityManager headers (shared identity "sm-carol")."""
    return TEST_USERS["manager_headers"]


@pytest.fixture
def verifier_headers() -> dict:
    """Verifier headers (shared identity "ver-dana" — distinct from the
    standard submitter identity, so segregation-of-duties gates pass)."""
    return TEST_USERS["verifier_headers"]


@pytest.fixture
def approver_headers() -> dict:
    """ClaimsApprover headers (shared identity "ap-erin" — distinct from the
    standard claim-creator identity)."""
    return TEST_USERS["approver_headers"]


@pytest.fixture
def specifier_headers() -> dict:
    """Specifier headers (shared identity "spec-ada"). Ownership-gated calls
    must instead use make_specifier_headers(resource["created_by"])."""
    return TEST_USERS["specifier_headers"]


@pytest.fixture
def installer_headers() -> dict:
    """Installer headers (shared identity "inst-bob"). Ownership-gated calls
    must instead use make_installer_headers(site["contractor_name"])."""
    return TEST_USERS["installer_headers"]
