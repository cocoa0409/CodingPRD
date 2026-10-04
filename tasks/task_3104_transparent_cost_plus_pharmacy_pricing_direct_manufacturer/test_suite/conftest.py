"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH and server lifecycle; these fixtures are a thin
bridge so tests can request `api` and role headers by name.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS, make_patient_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def ops_headers():
    """PharmacyOps operator headers (opaque identity)."""
    return TEST_USERS["pharmacy_ops_headers"]


@pytest.fixture
def pharmacist_headers():
    """Pharmacist headers (opaque identity)."""
    return TEST_USERS["pharmacist_headers"]


@pytest.fixture
def anonymous_headers():
    """Anonymous caller headers — only the liveness probe admits them."""
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def patient_headers_factory():
    """Build Patient headers bound to a real Patient entity id."""
    return make_patient_headers