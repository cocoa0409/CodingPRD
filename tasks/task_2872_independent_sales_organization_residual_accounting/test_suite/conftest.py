"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle and the ``PYTHONPATH``, so ``test_helpers``
imports directly. The database is empty and the logical clock reads
``2026-08-01T00:00:00Z`` at the start of every test.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def iso_admin_headers() -> dict:
    """The ISO back-office operator: all master data and the logical clock."""
    return TEST_USERS["iso_admin_headers"]


@pytest.fixture
def residual_analyst_headers() -> dict:
    """The residual operations analyst: ingest, normalize, chargebacks."""
    return TEST_USERS["residual_analyst_headers"]


@pytest.fixture
def residual_controller_headers() -> dict:
    """The residual controller: the only role that moves money."""
    return TEST_USERS["residual_controller_headers"]


@pytest.fixture
def agent_headers() -> dict:
    """A sales agent acting on its own book; use make_agent_headers for ownership."""
    return TEST_USERS["agent_headers"]
