"""Pytest fixtures exposing the `test_helpers` infrastructure.

The runner puts the task root on `PYTHONPATH`, so `test_helpers` imports
without any `sys.path` manipulation. The harness relaunches the API server
before every individual test, so each test starts against an empty database
and every fixture below rebuilds whatever state it needs.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client
from test_helpers.fixtures import (
    ADMIN,
    COORDINATOR,
    COUNSELOR,
    COUNSELOR_TWO,
    REVIEWER,
    Scenario,
    active_episode,
    bootstrap_reference,
    planned_episode,
    scheduled_dose,
    visit_ready_practice,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's business."""
    return api_client


# ---------------------------------------------------------------------------
# One headers fixture per role (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def registry_admin_headers():
    return TEST_USERS["registry_admin_headers"]


@pytest.fixture
def prior_auth_coordinator_headers():
    return TEST_USERS["prior_auth_coordinator_headers"]


@pytest.fixture
def payer_reviewer_headers():
    return TEST_USERS["payer_reviewer_headers"]


@pytest.fixture
def benefits_counselor_headers():
    return TEST_USERS["benefits_counselor_headers"]


@pytest.fixture
def second_benefits_counselor_headers():
    return TEST_USERS["benefits_counselor_second_headers"]


@pytest.fixture
def rheumatologist_headers():
    """A `Rheumatologist` identity with no clinician row behind it — safe only
    for tests that never reach an ownership or credential comparison."""
    return TEST_USERS["rheumatologist_headers"]


@pytest.fixture
def infusion_nurse_headers():
    return TEST_USERS["infusion_nurse_headers"]


@pytest.fixture
def patient_headers():
    return TEST_USERS["patient_headers"]


# ---------------------------------------------------------------------------
# Composite world fixtures (thin wrappers over test_helpers.fixtures).
# ---------------------------------------------------------------------------
@pytest.fixture
def reference() -> Scenario:
    """Rheumatologist, nurse, Infliximab, Meridian PPO and one open chair."""
    return bootstrap_reference()


@pytest.fixture
def practice() -> Scenario:
    """Reference data plus one consenting, unscreened patient."""
    return visit_ready_practice()


@pytest.fixture
def planned() -> Scenario:
    """A screened patient with one `PLANNED`, `UNFUNDED` episode."""
    return planned_episode()


@pytest.fixture
def active() -> Scenario:
    """An `ACTIVE`, `AUTHORIZED`, monitoring-`CURRENT` episode with six
    approved units and an open ambulatory chair."""
    return active_episode()


@pytest.fixture
def dosed() -> Scenario:
    """An `ACTIVE` episode with one `SCHEDULED` dose at 2026-08-12T09:00Z."""
    return scheduled_dose()
