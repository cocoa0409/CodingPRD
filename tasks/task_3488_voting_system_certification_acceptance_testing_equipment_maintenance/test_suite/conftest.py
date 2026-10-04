"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; the server is rebooted via
start.sh before every test, so fixtures build all state through the API.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def certification_authority_headers() -> dict:
    return TEST_USERS["certification_authority_headers"]


@pytest.fixture
def vendor_rep_headers() -> dict:
    return TEST_USERS["vendor_rep_headers"]


@pytest.fixture
def lab_agent_headers() -> dict:
    """Shared LabAgent fallback identity — non-ownership probes only. For any
    ownership-gated call use make_lab_agent_headers(lab["id"]) instead."""
    return TEST_USERS["lab_agent_headers"]


@pytest.fixture
def election_official_headers() -> dict:
    """Shared ElectionOfficial fallback identity — non-ownership probes only.
    For any ownership-gated call use
    make_election_official_headers(official["id"]) instead."""
    return TEST_USERS["election_official_headers"]


@pytest.fixture
def auditor_headers() -> dict:
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def public_requester_headers() -> dict:
    return TEST_USERS["public_requester_headers"]
