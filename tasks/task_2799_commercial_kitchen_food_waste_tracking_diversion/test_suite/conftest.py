"""Shared pytest fixtures for the food waste tracking and diversion suite."""

import sys
from pathlib import Path
from typing import Callable, Dict

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_helpers import (  # noqa: E402
    ApiClient,
    make_corporate_lead_headers,
    make_hauler_operator_headers,
    make_kitchen_staff_headers,
    make_platform_admin_headers,
    make_shift_lead_headers,
    make_site_sustainability_manager_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The endpoint-per-method client every test drives the service through."""
    return ApiClient()


@pytest.fixture
def kitchen_staff_headers() -> Dict[str, str]:
    """A line or prep cook at a station terminal."""
    return make_kitchen_staff_headers("ks-1")


@pytest.fixture
def other_kitchen_staff_headers() -> Dict[str, str]:
    return make_kitchen_staff_headers("ks-2")


@pytest.fixture
def shift_lead_headers() -> Dict[str, str]:
    """The supervisor of one service period."""
    return make_shift_lead_headers("sl-1")


@pytest.fixture
def other_shift_lead_headers() -> Dict[str, str]:
    """A second ShiftLead identity, which the void duty separation requires."""
    return make_shift_lead_headers("sl-2")


@pytest.fixture
def site_manager_headers() -> Callable[[str], Dict[str, str]]:
    """``X-User-ID`` for a SiteSustainabilityManager is the id of the acting Site."""
    return make_site_sustainability_manager_headers


@pytest.fixture
def hauler_operator_headers() -> Callable[[str], Dict[str, str]]:
    """``X-User-ID`` for a HaulerOperator is the id of the acting Hauler."""
    return make_hauler_operator_headers


@pytest.fixture
def corporate_lead_headers() -> Dict[str, str]:
    return make_corporate_lead_headers("csl-1")


@pytest.fixture
def other_corporate_lead_headers() -> Dict[str, str]:
    """A second CorporateSustainabilityLead identity, which publication requires."""
    return make_corporate_lead_headers("csl-2")


@pytest.fixture
def platform_admin_headers() -> Dict[str, str]:
    """The maintainer of the shared catalog."""
    return make_platform_admin_headers("pa-1")
