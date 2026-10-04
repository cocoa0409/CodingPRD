"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the API server before every individual test and injects
API_BASE_URL; fixtures below only bridge test_helpers into pytest. For
entity-backed roles (LeadStateAG / ParticipatingStateAG / StateLegislature)
these shared headers are safe only for tests that do not exercise office
ownership — ownership-gated calls must build per-instance headers with
test_helpers.make_lead_state_ag_headers(office_id) etc.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def committee_chair_headers():
    return TEST_USERS["committee_chair_headers"]


@pytest.fixture
def lead_state_ag_headers():
    return TEST_USERS["lead_state_ag_headers"]


@pytest.fixture
def participating_state_ag_headers():
    return TEST_USERS["participating_state_ag_headers"]


@pytest.fixture
def defendant_counsel_headers():
    return TEST_USERS["defendant_counsel_headers"]


@pytest.fixture
def fund_administrator_headers():
    return TEST_USERS["fund_administrator_headers"]


@pytest.fixture
def state_legislature_headers():
    return TEST_USERS["state_legislature_headers"]


@pytest.fixture
def compliance_monitor_headers():
    return TEST_USERS["compliance_monitor_headers"]
