"""Pytest fixtures exposing the test_helpers infrastructure.

The runner restarts the API server before every test and injects API_BASE_URL,
so every test starts against an empty database (PRD 2.4 boot clock
2026-09-01T00:00:00Z) and builds its own world through the public API.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture()
def api() -> ApiClient:
    """Shared API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture()
def planner_admin_headers() -> dict:
    return TEST_USERS["planner_admin_headers"]


@pytest.fixture()
def service_agent_headers() -> dict:
    return TEST_USERS["service_agent_headers"]


@pytest.fixture()
def app_user_headers() -> dict:
    return TEST_USERS["app_user_headers"]


@pytest.fixture()
def channel_rep_headers() -> dict:
    """Shared ChannelRep headers — non-ownership probes only (PRD 2.1)."""
    return TEST_USERS["channel_rep_headers"]


@pytest.fixture()
def assembler_headers() -> dict:
    """Shared Assembler headers — non-ownership probes only (PRD 2.1)."""
    return TEST_USERS["assembler_headers"]
