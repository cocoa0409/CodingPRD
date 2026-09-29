"""Shared pytest wiring for the Hotel Channel Distribution suite.

The harness restarts the API server before each test, so every test starts
against an empty database whose logical clock sits at the declared start instant,
and builds the world it needs through the public API. The base URL is injected
into the environment by the runner, so the client is constructed with no
arguments.
"""

import pytest

from test_helpers import ApiClient, fixtures


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def world(api: ApiClient):
    """The canonical world: one property, one room type, one live OTA, one active plan.

    The logical clock is parked first, so every scenario dates its stays from a
    known day rather than from the server's start instant.
    """
    return fixtures.seed_reference_data(api)
