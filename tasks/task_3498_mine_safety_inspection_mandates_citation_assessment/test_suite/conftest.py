"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns PYTHONPATH and the API server lifecycle (the server is
restarted against an empty database before every test, so each test builds its
entire world through PRD §4 endpoints). Tests import domain helpers straight
from ``test_helpers`` and take the ``api`` fixture for direct endpoint calls.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]


@pytest.fixture
def district_manager_headers() -> dict:
    return TEST_USERS["district_manager_headers"]


@pytest.fixture
def inspector_headers() -> dict:
    """Shared Inspector headers — fallback only for calls whose outcome cannot
    depend on Inspector-entity ownership (PRD §2.1); ownership-gated calls must
    use make_inspector_headers(inspector["id"])."""
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def operator_rep_headers() -> dict:
    """Shared OperatorRep headers — fallback only (see inspector_headers)."""
    return TEST_USERS["operator_rep_headers"]


@pytest.fixture
def commission_judge_headers() -> dict:
    return TEST_USERS["commission_judge_headers"]


@pytest.fixture
def public_reader_headers() -> dict:
    return TEST_USERS["public_reader_headers"]
