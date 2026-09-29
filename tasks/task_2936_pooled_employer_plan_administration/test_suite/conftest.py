"""
Shared pytest wiring for the Pooled Employer Plan administration suite.

The harness restarts the API server before each test, so every test starts
against an empty database and builds the world it needs through the public API.
The base URL is injected into the environment by the runner, so the client is
constructed with no arguments.
"""

import pytest

from test_helpers import ApiClient, fixtures
from test_helpers.fixtures import EmployerContext, PlanContext


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def draft_plan(api: ApiClient) -> PlanContext:
    """A registered sponsor and a DRAFT plan whose two functions are acknowledged."""
    return fixtures.plan_with_acknowledged_roles(api)


@pytest.fixture()
def plan(api: ApiClient) -> PlanContext:
    """An ACTIVE plan with its sponsor, recordkeeper, trustee and allocations."""
    return fixtures.active_plan(api)


@pytest.fixture()
def employer(api: ApiClient, plan: PlanContext) -> EmployerContext:
    """An ACTIVE adopting employer with an APPROVED safe-harbour election."""
    return fixtures.active_employer(api, plan)


@pytest.fixture()
def second_employer(api: ApiClient, plan: PlanContext) -> EmployerContext:
    """A second ACTIVE adopting employer on the same plan."""
    return fixtures.second_active_employer(api, plan)


@pytest.fixture()
def batch(api: ApiClient, employer: EmployerContext) -> dict:
    """A VALIDATED payroll batch for the canonical pay period."""
    return fixtures.validated_batch(api, employer)


@pytest.fixture()
def audit_firm(api: ApiClient, plan: PlanContext) -> dict:
    """An audit firm engaged on the plan."""
    return fixtures.audit_firm(api, plan)
