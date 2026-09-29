"""
Shared pytest wiring for the Early Intervention Service Coordination suite.

Every test runs against a freshly started server with an empty database, so the
client is built per test and all state is created through the public API. The
composite case builders live in ``test_helpers.fixtures``; the pytest fixtures
they define are re-exported here so pytest can resolve them by name from any
test module.
"""

import pytest

from test_helpers import ApiClient
from test_helpers.test_users import (
    ADMIN_HEADERS,
    EVALUATOR_HEADERS,
    FISCAL_2_HEADERS,
    FISCAL_HEADERS,
    INTAKE_HEADERS,
)

# Re-exported so pytest discovers the staged case fixtures defined alongside
# the builders. Each of these depends on the ``api`` fixture below.
from test_helpers.fixtures import (  # noqa: F401
    active_services_case,
    assigned_case,
    authorized_case,
    delivered_visit_case,
    ifsp_pending_case,
    intake_case,
    plan_with_line_case,
    visit_scheduled_case,
)


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the server under test for the duration of one test."""
    return ApiClient()


@pytest.fixture
def intake_headers():
    return dict(INTAKE_HEADERS)


@pytest.fixture
def admin_headers():
    return dict(ADMIN_HEADERS)


@pytest.fixture
def evaluator_headers():
    return dict(EVALUATOR_HEADERS)


@pytest.fixture
def fiscal_headers():
    return dict(FISCAL_HEADERS)


@pytest.fixture
def second_fiscal_headers():
    return dict(FISCAL_2_HEADERS)
