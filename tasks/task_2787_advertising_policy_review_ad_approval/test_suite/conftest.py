"""Shared pytest fixtures for the advertising policy review suite.

The runner owns the server lifecycle and hands every test a freshly started
process, so each test begins against an empty database with the logical clock at
`2026-08-01T00:00:00Z` (PRD §2.8). Preconditions are therefore always built
through the declared endpoints rather than seeded directly.
"""

import pytest

from test_helpers import ADMIN, ANALYST, api_client


@pytest.fixture(scope="session")
def api():
    """The shared HTTP client bound to the runner-supplied base URL."""
    return api_client


@pytest.fixture
def policy_admin_headers():
    """PolicyAdmin identity: opaque, never compared to a stored id (PRD §2.1)."""
    return ADMIN


@pytest.fixture
def integrity_analyst_headers():
    """IntegrityAnalyst identity: opaque, never compared to a stored id (PRD §2.1)."""
    return ANALYST
