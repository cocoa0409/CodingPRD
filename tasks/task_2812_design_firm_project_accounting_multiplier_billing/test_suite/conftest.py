"""
Shared pytest fixtures for the design-firm project accounting API contract suite.

The logical clock is deliberately NOT pinned by an autouse fixture. PRD §2.6
gives the clock a documented starting instant of 2026-08-01T00:00:00Z before it
is ever set explicitly, and that default is itself part of the contract, so a
test that wants a different instant moves the clock itself — every composite
builder in test_helpers does exactly that as its first call.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.constants import CLOCK_2026_06_01  # noqa: E402
from test_helpers.fixtures import (  # noqa: E402,F401
    build_active_project,
    build_certified_public_project,
    build_closed_project,
    build_project_at_review_required,
    build_project_with_labor,
    create_private_client,
    create_public_client,
    publish_labor_rate,
    set_clock,
)
from test_helpers.test_users import (  # noqa: E402
    ACCOUNTANT,
    CONTROLLER,
    FIRM_ADMIN,
    PROJECT_MANAGER,
)


@pytest.fixture
def api() -> ApiClient:
    """
    The endpoint client. The server is relaunched before every individual test,
    so each test starts against an empty database and stands up all of its own
    state through the PRD's own endpoints.
    """
    return ApiClient()


@pytest.fixture
def clock_june(api):
    """The logical clock pinned to 2026-06-01T00:00:00Z, so 2026 is the fiscal year."""
    return set_clock(api, CLOCK_2026_06_01)


@pytest.fixture
def firm_admin():
    """A FirmAdmin's headers; the logical clock is theirs alone."""
    return FIRM_ADMIN


@pytest.fixture
def controller():
    """A Controller's headers."""
    return CONTROLLER


@pytest.fixture
def project_manager():
    """The owning ProjectManager's headers."""
    return PROJECT_MANAGER


@pytest.fixture
def accountant():
    """A ProjectAccountant's headers."""
    return ACCOUNTANT


@pytest.fixture
def private_client(api, clock_june):
    """The canonical private practice client."""
    return create_private_client(api)


@pytest.fixture
def public_client(api, clock_june):
    """The canonical public agency client."""
    return create_public_client(api)


@pytest.fixture
def architect_rate(api, clock_june):
    """PROJECT_ARCHITECT at a raw cost rate of 62.50 from 2026-01-01, open-ended."""
    return publish_labor_rate(api)


@pytest.fixture
def active_project(api):
    """An ACTIVE private-client project with one LUMP_SUM leaf phase."""
    return build_active_project(api)


@pytest.fixture
def active_fixed_fee_project(api):
    """An ACTIVE FIXED_FEE project, the only contract type under the earned-value ceiling."""
    return build_active_project(
        api,
        project_overrides={"contract_type": "FIXED_FEE", "name": "Civic Center Addition"},
    )


@pytest.fixture
def active_assessed_project(api):
    """An ACTIVE project whose percent-complete method is ASSESSED."""
    return build_active_project(
        api,
        project_overrides={
            "percent_complete_method": "ASSESSED",
            "name": "Harbor Master Plan",
        },
    )


@pytest.fixture
def project_with_labor(api):
    """An ACTIVE project carrying 3307.36 of approved unbilled labour."""
    return build_project_with_labor(api)


@pytest.fixture
def review_required_project(api):
    """A project whose unbilled work in progress has moved it to REVIEW_REQUIRED."""
    return build_project_at_review_required(api)


@pytest.fixture
def certified_public_project(api):
    """A public-agency project with fiscal 2026 certified, so its posture is OPEN."""
    return build_certified_public_project(api)


@pytest.fixture
def closed_project(api):
    """A project the bubble-up rule of PRD §3.6 has driven to CLOSED."""
    return build_closed_project(api)
