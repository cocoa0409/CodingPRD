"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; this file only wires the
shared API client and the role headers into fixtures.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's business."""
    return api_client


@pytest.fixture
def bureau_admin_headers():
    return TEST_USERS["bureau_admin_headers"]


@pytest.fixture
def model_developer_headers():
    return TEST_USERS["model_developer_headers"]


@pytest.fixture
def validation_analyst_headers():
    return TEST_USERS["validation_analyst_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def fair_lending_officer_headers():
    return TEST_USERS["fair_lending_officer_headers"]


@pytest.fixture
def reason_code_admin_headers():
    return TEST_USERS["reason_code_admin_headers"]


@pytest.fixture
def score_consumer_headers():
    return TEST_USERS["score_consumer_headers"]


@pytest.fixture
def unknown_role_headers():
    return TEST_USERS["unknown_role_headers"]