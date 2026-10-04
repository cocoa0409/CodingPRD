"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns the server lifecycle and PYTHONPATH; this file only wires the
generated helpers into pytest's fixture graph.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def advisor_headers():
    return TEST_USERS["delivery_advisor_headers"]


@pytest.fixture
def trade_in_headers():
    return TEST_USERS["trade_in_specialist_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_partner_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["service_technician_headers"]


@pytest.fixture
def parts_headers():
    return TEST_USERS["parts_coordinator_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]