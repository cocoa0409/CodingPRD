"""
Shared pytest fixtures for the retina buy-and-bill suite.

The service is restarted before every individual test, so every fixture here is
function scoped: a client holding a keep-alive connection to a process that has
since been replaced would fail on its first call, and any state a previous test
built is gone.  Each test therefore starts from an empty database and builds
exactly the rows it needs.
"""

import os
import sys
from typing import Dict, Iterator

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    BreadthWorld,
    DepthWorld,
    admin_headers,
    billing_headers,
    compliance_headers,
    tech_headers,
)
from test_helpers.constants import DEFAULT_CLOCK  # noqa: E402


@pytest.fixture()
def api() -> Iterator[ApiClient]:
    """An HTTP client bound to the service under test."""
    client = ApiClient()
    yield client
    client.session.close()


@pytest.fixture()
def admin() -> Dict[str, str]:
    """``PracticeAdmin`` headers."""
    return admin_headers()


@pytest.fixture()
def tech() -> Dict[str, str]:
    """``PharmacyTech`` headers."""
    return tech_headers()


@pytest.fixture()
def billing() -> Dict[str, str]:
    """``BillingSpecialist`` headers."""
    return billing_headers()


@pytest.fixture()
def compliance() -> Dict[str, str]:
    """``ComplianceOfficer`` headers."""
    return compliance_headers()


@pytest.fixture()
def depth(api: ApiClient) -> DepthWorld:
    """
    The depth cast with the logical clock parked at the suite's default instant.

    The clock is set first so that every row created afterwards is stamped from
    the same instant and every windowed calculation is evaluated inside the
    window the fixtures were built for.
    """
    world = DepthWorld(api)
    world.set_clock(DEFAULT_CLOCK)
    return world


@pytest.fixture()
def breadth(api: ApiClient) -> BreadthWorld:
    """The breadth cast with the logical clock parked at the default instant."""
    world = BreadthWorld(api)
    world.set_clock(DEFAULT_CLOCK)
    return world
