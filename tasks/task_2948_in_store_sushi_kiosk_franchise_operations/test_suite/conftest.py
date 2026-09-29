"""Pytest fixtures exposing the test_helpers infrastructure to every test file.

The harness restarts the API server before each test, so no fixture here caches
domain state; only the HTTP client is reused.
"""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_franchisor_ops_headers,
    make_quality_auditor_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def ops_headers() -> dict:
    """Headers for the default opaque franchisor operations identity."""
    return make_franchisor_ops_headers()


@pytest.fixture
def ops_issuer_headers() -> dict:
    """Headers for a second, distinct franchisor operations identity."""
    return TEST_USERS["franchisor_ops_issuer_headers"]


@pytest.fixture
def auditor_headers() -> dict:
    """Headers for the default opaque quality auditor identity."""
    return make_quality_auditor_headers()


@pytest.fixture
def auditor_verifier_headers() -> dict:
    """Headers for a second, distinct quality auditor identity."""
    return TEST_USERS["quality_auditor_verifier_headers"]
