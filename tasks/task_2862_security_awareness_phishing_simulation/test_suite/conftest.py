"""Shared pytest fixtures for the Security Awareness & Phishing Simulation suite.

The harness relaunches the service against an empty database before each test,
so the logical clock is back at its declared start instant and no rows exist.
Every test therefore builds its own preconditions through the helpers in
``test_helpers.fixtures``.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient, api_client  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADMIN,
    ANALYST,
    APPROVER,
    AUTHOR,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client under test."""
    return api_client


@pytest.fixture
def admin() -> dict:
    """ProgramAdmin auth headers."""
    return ADMIN


@pytest.fixture
def author() -> dict:
    """CampaignAuthor auth headers for the canonical author identity."""
    return AUTHOR


@pytest.fixture
def approver() -> dict:
    """CampaignApprover auth headers for the canonical approver identity."""
    return APPROVER


@pytest.fixture
def analyst() -> dict:
    """SecurityAnalyst auth headers."""
    return ANALYST
