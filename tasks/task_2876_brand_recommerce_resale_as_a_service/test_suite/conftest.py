"""Shared pytest fixtures for the brand recommerce test suite.

The harness restarts the API server before every individual test, so each test
observes an empty database and builds every precondition it needs from scratch
through the platform's own endpoints.

The logical clock is part of that empty state: PRD §2.4 fixes it at
``2026-08-01T00:00:00Z`` before any client has set it, so tests that do not care
about time simply rely on that reading and tests that walk days forward move it
explicitly.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ADMIN,
    AUTH1,
    AUTH2,
    INTAKE,
    MERCH,
    TECH1,
    TECH2,
    api_client,
    make_customer_headers,
)


@pytest.fixture(scope="session")
def api():
    """The API client, one instance per session."""
    return api_client


@pytest.fixture
def admin_headers():
    """A ``ProgramAdmin`` caller: programme configuration and reporting."""
    return ADMIN


@pytest.fixture
def intake_agent_headers():
    """An ``IntakeAgent`` caller: takes physical custody at the counter."""
    return INTAKE


@pytest.fixture
def authenticator_headers():
    """An ``Authenticator`` caller: grades and dispositions a trade-in."""
    return AUTH1


@pytest.fixture
def second_authenticator_headers():
    """A second ``Authenticator``, needed for an independent re-grade."""
    return AUTH2


@pytest.fixture
def refurb_technician_headers():
    """A ``RefurbTechnician`` caller: books bays and logs effort."""
    return TECH1


@pytest.fixture
def second_refurb_technician_headers():
    """A second ``RefurbTechnician``, needed to sign another's work off."""
    return TECH2


@pytest.fixture
def merchandising_manager_headers():
    """A ``MerchandisingManager`` caller: lists, marks down and settles."""
    return MERCH


@pytest.fixture
def customer_headers_for():
    """Build ``Customer`` headers bound to a particular participant row."""
    return make_customer_headers
