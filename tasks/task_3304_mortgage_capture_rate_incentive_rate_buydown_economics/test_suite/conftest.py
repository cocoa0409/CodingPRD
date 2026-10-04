"""Shared pytest wiring for the mortgage capture and rate buydown suite.

The harness restarts the API server before each test, so every test starts
against an empty database and builds the world it needs through the public API.
The base URL is injected into the environment by the runner, so the client is
constructed with no arguments.
"""

import pytest

from test_helpers import ApiClient
from test_helpers import fixtures


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def world(api: ApiClient):
    """Reference data: the clock at its startup default, a community under the
    standard policy, a buyer, one inventory home and one forward commitment."""
    return fixtures.seed_reference_data(api)


@pytest.fixture()
def deal(api: ApiClient):
    """Reference data plus a PENDING contract and a QUALIFIED affiliated application."""
    return fixtures.build_deal(api)