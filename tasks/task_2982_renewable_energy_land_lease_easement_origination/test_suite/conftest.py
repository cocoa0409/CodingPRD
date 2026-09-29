"""Pytest fixtures exposing the Renewable Land Origination test infrastructure."""

import pytest

from test_helpers import LandOriginationApiClient
from test_helpers.constants import CLOCK_START
from test_helpers.fixtures import caprock_qualified_parcel, client, register_landowner


@pytest.fixture(scope="session")
def api() -> LandOriginationApiClient:
    """Session-scoped endpoint client. Server lifecycle is the runner's business."""
    return client()


@pytest.fixture
def clock_start() -> str:
    """The instant the logical clock reads on a freshly booted server."""
    return CLOCK_START


@pytest.fixture
def landowner():
    """One registered owner of record."""
    return register_landowner()


@pytest.fixture
def caprock():
    """An owner, their county's three ordinances, and one qualified parcel."""
    return caprock_qualified_parcel()
