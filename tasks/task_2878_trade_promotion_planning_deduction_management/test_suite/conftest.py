"""
Pytest bridge between the test modules and the shared test helpers.

The harness relaunches the service before every individual test, so each test
starts against an empty database and builds all of its preconditions from the
endpoints the PRD declares.
"""

import os
import sys
from typing import Dict

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient, api_client  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ANALYST_ALT_HEADERS,
    ANALYST_HEADERS,
    AUDITOR_ALT_HEADERS,
    AUDITOR_HEADERS,
    DIRECTOR_ALT_HEADERS,
    DIRECTOR_HEADERS,
    KAM_ALT_HEADERS,
    KAM_HEADERS,
    SPECIALIST_ALT_HEADERS,
    SPECIALIST_HEADERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The typed HTTP client for the service under test."""
    return api_client


@pytest.fixture
def director() -> Dict[str, str]:
    """Headers for a `TradeMarketingDirector`."""
    return DIRECTOR_HEADERS


@pytest.fixture
def director_alt() -> Dict[str, str]:
    """Headers for a second, distinct `TradeMarketingDirector` operator."""
    return DIRECTOR_ALT_HEADERS


@pytest.fixture
def key_account_manager() -> Dict[str, str]:
    """Headers for a `KeyAccountManager`."""
    return KAM_HEADERS


@pytest.fixture
def key_account_manager_alt() -> Dict[str, str]:
    """Headers for a second, distinct `KeyAccountManager` operator."""
    return KAM_ALT_HEADERS


@pytest.fixture
def finance_analyst() -> Dict[str, str]:
    """Headers for a `TradeFinanceAnalyst`."""
    return ANALYST_HEADERS


@pytest.fixture
def finance_analyst_alt() -> Dict[str, str]:
    """Headers for a second, distinct `TradeFinanceAnalyst` operator."""
    return ANALYST_ALT_HEADERS


@pytest.fixture
def deduction_specialist() -> Dict[str, str]:
    """Headers for a `DeductionSpecialist`."""
    return SPECIALIST_HEADERS


@pytest.fixture
def deduction_specialist_alt() -> Dict[str, str]:
    """Headers for a second, distinct `DeductionSpecialist` operator."""
    return SPECIALIST_ALT_HEADERS


@pytest.fixture
def compliance_auditor() -> Dict[str, str]:
    """Headers for a `ComplianceAuditor`."""
    return AUDITOR_HEADERS


@pytest.fixture
def compliance_auditor_alt() -> Dict[str, str]:
    """Headers for a second, distinct `ComplianceAuditor` operator."""
    return AUDITOR_ALT_HEADERS
