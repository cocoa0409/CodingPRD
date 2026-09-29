"""Shared pytest wiring for the Executive Protection & Travel Risk Management suite.

The harness restarts the API server before every test, so each test starts
against empty storage and builds the world it needs through the published
endpoints.  The base URL is injected into the environment by the runner, so the
client is constructed with no arguments.
"""

import pytest

from test_helpers import ExecProtectionClient
from test_helpers import fixtures as fx


@pytest.fixture()
def api() -> ExecProtectionClient:
    """A client aimed at the server under test."""
    return ExecProtectionClient()


@pytest.fixture()
def dep(api):
    """The logical clock at its startup default and the four staff members."""
    return fx.bootstrap_department(api)


@pytest.fixture()
def world(api):
    """A protectee with a complete survey, a `LOW` `PT` advisory, verified cover
    and one approved risk assessment."""
    return fx.bootstrap_world(api)
