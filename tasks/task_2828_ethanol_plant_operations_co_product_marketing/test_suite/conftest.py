"""
Shared pytest wiring for the Ethanol Plant Operations compliance suite.

The runner relaunches the server before every test, so each test starts against
an empty database and builds all of its own state through the endpoints of PRD
section 4.  Nothing here caches server state between tests.
"""

import os
import sys

import pytest

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers import EthanolOpsApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    COMPLIANCE_OFFICER,
    GRAIN_ACCOUNTANT,
    GRAIN_BUYER,
    LOGISTICS_COORDINATOR,
    PLANT_MANAGER,
    PROCESS_OPERATOR,
    RISK_MANAGER,
    SCALE_OPERATOR,
)


@pytest.fixture(scope="session")
def api() -> EthanolOpsApiClient:
    """One stateless client, pointed at API_BASE_URL by the runner."""
    return EthanolOpsApiClient()


@pytest.fixture
def plant_manager():
    return PLANT_MANAGER


@pytest.fixture
def grain_buyer():
    return GRAIN_BUYER


@pytest.fixture
def scale_operator():
    return SCALE_OPERATOR


@pytest.fixture
def grain_accountant():
    return GRAIN_ACCOUNTANT


@pytest.fixture
def process_operator():
    return PROCESS_OPERATOR


@pytest.fixture
def logistics_coordinator():
    return LOGISTICS_COORDINATOR


@pytest.fixture
def compliance_officer():
    return COMPLIANCE_OFFICER


@pytest.fixture
def risk_manager():
    return RISK_MANAGER
