"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable without sys.path
hacks, owns the server lifecycle, and injects API_BASE_URL. Session-scoped for
the API client, function-scoped for role headers.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def supply_planner_headers():
    return TEST_USERS["supply_planner_headers"]


@pytest.fixture
def customer_ops_headers():
    """FALLBACK CustomerOps identity (not entity-backed to any real Customer).
    Use only for tests whose outcome does not depend on customer ownership;
    ownership-gated calls must build headers with
    make_customer_ops_headers(customer["id"])."""
    return TEST_USERS["customer_ops_headers"]


@pytest.fixture
def plant_operator_headers():
    return TEST_USERS["plant_operator_headers"]


@pytest.fixture
def pipeline_dispatcher_headers():
    return TEST_USERS["pipeline_dispatcher_headers"]


@pytest.fixture
def telemetry_gateway_headers():
    return TEST_USERS["telemetry_gateway_headers"]


@pytest.fixture
def quality_analyst_headers():
    return TEST_USERS["quality_analyst_headers"]


@pytest.fixture
def quality_certifier_headers():
    return TEST_USERS["quality_certifier_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]
