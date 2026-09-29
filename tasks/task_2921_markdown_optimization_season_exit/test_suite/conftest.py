"""Shared pytest fixtures for the Markdown Optimization & Season Exit suite.

The harness restarts the server before every individual test, so each test
starts against an empty database and builds the whole world it needs.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ANALYST_HEADERS,
    ANALYST_TWO_HEADERS,
    CONTROLLER_HEADERS,
    CONTROLLER_TWO_HEADERS,
    DIRECTOR_HEADERS,
    DIRECTOR_TWO_HEADERS,
    VENDOR_REP_HEADERS,
    VENDOR_REP_TWO_HEADERS,
    api_client,
)


@pytest.fixture(scope="session")
def api():
    """The HTTP client for the API under test."""
    return api_client


@pytest.fixture
def analyst():
    """Headers for the pricing analyst who owns the markdown mechanics."""
    return ANALYST_HEADERS


@pytest.fixture
def analyst_two():
    """Headers for a second, distinct pricing analyst."""
    return ANALYST_TWO_HEADERS


@pytest.fixture
def director():
    """Headers for the merchandise director who owns the registry and review."""
    return DIRECTOR_HEADERS


@pytest.fixture
def director_two():
    """Headers for a second, distinct merchandise director."""
    return DIRECTOR_TWO_HEADERS


@pytest.fixture
def vendor_rep():
    """Headers for the vendor representative at the negotiation table."""
    return VENDOR_REP_HEADERS


@pytest.fixture
def vendor_rep_two():
    """Headers for a second, distinct vendor representative."""
    return VENDOR_REP_TWO_HEADERS


@pytest.fixture
def controller():
    """Headers for the controller who owns the money."""
    return CONTROLLER_HEADERS


@pytest.fixture
def controller_two():
    """Headers for a second, distinct controller."""
    return CONTROLLER_TWO_HEADERS
