"""Shared pytest fixtures for the Essential Air Service Subsidy API suite.

The harness restarts the API against an empty database before every single
test, so no fixture here may assume state left by another test.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def reference(api: ApiClient):
    """Community + determination + aircraft type + two carriers + fuel index."""
    return fx.make_reference_data(api)


@pytest.fixture
def open_solicitation(api: ApiClient, reference):
    """An OPEN solicitation for the eligible community."""
    return fx.open_solicitation(api, reference.community_id)


@pytest.fixture
def award(api: ApiClient):
    """A single-candidate award: the booked ACTIVE service agreement."""
    return fx.build_award(api)
