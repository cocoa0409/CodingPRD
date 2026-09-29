"""
Pytest fixtures exposing the shared test infrastructure.

The API server is restarted with an empty database before each test, so every
fixture here is function-scoped and every precondition is built through the API
inside the test that needs it.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    make_design_critique_reviewer_headers,
    make_design_system_lead_headers,
    make_engineering_reviewer_headers,
    make_system_admin_headers,
)


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def admin():
    """Identity headers for the platform operator."""
    return make_system_admin_headers()


@pytest.fixture
def lead():
    """Identity headers for the design-system lead."""
    return make_design_system_lead_headers()


@pytest.fixture
def critic():
    """Identity headers for the design-critique gate reviewer."""
    return make_design_critique_reviewer_headers()


@pytest.fixture
def engineer():
    """Identity headers for the engineering-review gate reviewer."""
    return make_engineering_reviewer_headers()
