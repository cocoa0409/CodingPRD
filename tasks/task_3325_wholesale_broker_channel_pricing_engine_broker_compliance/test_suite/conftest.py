"""Pytest fixture bridge exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client
from test_helpers.test_users import (
    NAMED_QC_ANALYST_ID,
    NAMED_UNDERWRITER_ID,
    make_broker_headers,
    make_channel_manager_headers,
    make_compliance_officer_headers,
    make_platform_admin_headers,
    make_qc_analyst_headers,
    make_underwriter_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def channel_manager_headers():
    return TEST_USERS["channel_manager_headers"]


@pytest.fixture
def underwriting_headers():
    return make_underwriter_headers(NAMED_UNDERWRITER_ID)


@pytest.fixture
def compliance_headers():
    return make_compliance_officer_headers()


@pytest.fixture
def qc_headers():
    return make_qc_analyst_headers(NAMED_QC_ANALYST_ID)


@pytest.fixture
def platform_admin_headers():
    return make_platform_admin_headers()


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]


@pytest.fixture
def broker_headers():
    """Builder for ownership-gated broker-scoped calls."""
    return make_broker_headers