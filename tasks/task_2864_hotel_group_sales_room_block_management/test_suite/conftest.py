"""Pytest fixtures exposing the test_helpers infrastructure.

The server lifecycle is owned by the runner: every test starts against a
freshly launched service whose logical clock reads the mandated startup
default of PRD 2.4 and whose database is empty.
"""

import pytest

from test_helpers import ApiClient


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client aimed at the service under test."""
    return ApiClient()


@pytest.fixture
def sales_manager():
    """The group sales manager (PRD 2.1)."""
    from test_helpers import SALES_MANAGER

    return SALES_MANAGER


@pytest.fixture
def revenue_manager():
    """Revenue management, owner of the calendar and the concession catalogue."""
    from test_helpers import REVENUE_MANAGER

    return REVENUE_MANAGER


@pytest.fixture
def revenue_manager_alt():
    """A second revenue manager, needed wherever duties are segregated."""
    from test_helpers import REVENUE_MANAGER_ALT

    return REVENUE_MANAGER_ALT


@pytest.fixture
def contract_admin():
    """Contract administration (PRD 2.1)."""
    from test_helpers import CONTRACT_ADMIN

    return CONTRACT_ADMIN


@pytest.fixture
def reservations_agent():
    """The reservations desk (PRD 2.1)."""
    from test_helpers import RESERVATIONS_AGENT

    return RESERVATIONS_AGENT


@pytest.fixture
def accounting_clerk():
    """Group accounting, which prepares the settlement (PRD 2.1)."""
    from test_helpers import ACCOUNTING_CLERK

    return ACCOUNTING_CLERK


@pytest.fixture
def accounting_clerk_alt():
    """A second clerk, because finalizing is a different person's act."""
    from test_helpers import ACCOUNTING_CLERK_ALT

    return ACCOUNTING_CLERK_ALT


@pytest.fixture
def system_operator():
    """The operations identity that owns only the logical clock (PRD 2.4)."""
    from test_helpers import SYSTEM_OPERATOR

    return SYSTEM_OPERATOR
