"""Pytest fixtures exposing the night-audit test infrastructure.

The runner restarts the server before every test, so the API client is built
fresh per test and every test builds the state it needs from an empty database.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import NightAuditApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADMIN,
    AUDITOR,
    AUDITOR_2,
    CONTROLLER,
    CONTROLLER_2,
    FRONT_DESK,
    FRONT_DESK_2,
    REVENUE_MANAGER,
    REVENUE_MANAGER_2,
)


@pytest.fixture
def api() -> NightAuditApiClient:
    """A fresh client per test. The runner owns the server lifecycle."""
    return NightAuditApiClient()


@pytest.fixture
def admin():
    return ADMIN


@pytest.fixture
def auditor():
    return AUDITOR


@pytest.fixture
def auditor_2():
    return AUDITOR_2


@pytest.fixture
def front_desk():
    return FRONT_DESK


@pytest.fixture
def front_desk_2():
    return FRONT_DESK_2


@pytest.fixture
def revenue_manager():
    return REVENUE_MANAGER


@pytest.fixture
def revenue_manager_2():
    return REVENUE_MANAGER_2


@pytest.fixture
def controller():
    return CONTROLLER


@pytest.fixture
def controller_2():
    return CONTROLLER_2
