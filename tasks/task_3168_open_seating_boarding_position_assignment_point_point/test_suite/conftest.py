"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle (start/stop/restart per test) is owned by
prd-bench-local-runner; this module only wires the generated helpers into
pytest fixtures.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client pointing at API_BASE_URL."""
    return api_client


@pytest.fixture
def passenger_headers():
    """Fallback Passenger identity for requests that are not ownership-gated."""
    return TEST_USERS["passenger_headers"]


@pytest.fixture
def gate_agent_headers():
    return TEST_USERS["gate_agent_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]
