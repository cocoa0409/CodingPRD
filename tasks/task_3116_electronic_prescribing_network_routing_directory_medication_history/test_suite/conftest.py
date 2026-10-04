"""Pytest fixtures exposing test_helpers infrastructure.

The server's lifecycle, `API_BASE_URL` injection and `PYTHONPATH` are owned by
prd-bench-local-runner; this file only wires the generated helpers into fixtures.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# ─── Opaque roles: the shared constant is the canonical form ───

@pytest.fixture
def operator_headers():
    """NetworkOperator — directory, certification, routing reporting, fee settlement."""
    return TEST_USERS["network_operator_headers"]


@pytest.fixture
def hub_operator_headers():
    """HubOperator — history ingestion and batch driving."""
    return TEST_USERS["hub_operator_headers"]


@pytest.fixture
def patient_service_headers():
    """PatientService — consent grants and revocations."""
    return TEST_USERS["patient_service_headers"]


# ─── Entity-backed roles: shared constants for non-ownership calls only ───

@pytest.fixture
def admin_headers():
    """ParticipantAdmin shared constant — safe only where ownership is not exercised."""
    return TEST_USERS["participant_admin_headers"]


@pytest.fixture
def prescriber_headers():
    """Prescriber shared constant — safe only where ownership is not exercised."""
    return TEST_USERS["prescriber_headers"]


@pytest.fixture
def pharmacy_headers():
    """Pharmacy shared constant — safe only where ownership is not exercised."""
    return TEST_USERS["pharmacy_headers"]