"""Shared pytest wiring for the Neighborhood Camera Video Request &
Community Safety Portal suite.

The harness restarts the API server before each test, so every test starts
against an empty deployment and builds the world it needs through the public
API. The base URL is injected into the environment by the runner, so the client
is constructed with no arguments.
"""

import pytest

from test_helpers import ApiClient, fixtures


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def clock(api: ApiClient) -> str:
    """The logical clock pinned to the instant every scenario is built around."""
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    return fixtures.SCENARIO_CLOCK


@pytest.fixture()
def canvass(api: ApiClient):
    """A submitted canvass: one onboarded agency, one officer, three camera
    owners on the roster and three dispatched solicitations."""
    return fixtures.seed_standard_canvass(api)
