"""Pytest fixtures exposing the generated infrastructure.

The API server lifecycle is owned by prd-bench-local-runner: it is restarted
before every individual test, so each test starts against an empty database.
"""
import sys
from pathlib import Path

import pytest

# Make the generated helpers importable regardless of how pytest is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_helpers import api_client, ApiClient, TEST_USERS  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture(scope="session")
def system_operator_headers():
    return TEST_USERS["system_operator_headers"]


@pytest.fixture(scope="session")
def account_owner_headers():
    return TEST_USERS["account_owner_headers"]


@pytest.fixture(scope="session")
def backup_operator_headers():
    return TEST_USERS["backup_operator_headers"]


@pytest.fixture(scope="session")
def retention_officer_headers():
    return TEST_USERS["retention_officer_headers"]


@pytest.fixture(scope="session")
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]