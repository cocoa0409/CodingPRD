"""Shared pytest wiring for the tourism improvement district suite.

The suite runs under a per-test server, so every test rebuilds the whole state it
needs through the declared endpoints of the API.  Nothing here relies on state
left behind by another test, and nothing is written behind the API.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.api_client import ApiClient  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the base URL the runner publishes in the environment."""
    return ApiClient()


# --------------------------------------------------------------------------
# Composite state, each rebuilt from scratch for the test that asks for it
# --------------------------------------------------------------------------
@pytest.fixture
def proposed_district(api):
    """A PROPOSED district carrying the four-property Harbor Bay roll."""
    return fx.district_with_roll(api)


@pytest.fixture
def circulating_district(api):
    """A PETITION_CIRCULATING district with an OPEN formation drive already
    signed by the core full-service property."""
    ctx = fx.district_with_roll(api)
    fx.open_formation_drive(api, ctx)
    fx.sign(api, ctx, "b1_id")
    return ctx


@pytest.fixture
def formed_district(api):
    """A FORMED district: drive signed, tallied qualified and certified."""
    return fx.formed_district(api)


@pytest.fixture
def active_district(api):
    """An ACTIVE district, which is what every assessment workflow needs."""
    return fx.active_district(api)


@pytest.fixture
def period_with_statements(api):
    """An ACTIVE district with an OPEN period holding one statement per
    property."""
    return fx.period_with_statements(api)


@pytest.fixture
def statements_filed(api):
    """The canonical filed pair: 2000 nights on 41225000 cents and 600 nights on
    20000000 cents, assessing 824500 and 340000."""
    return fx.statements_filed(api)


@pytest.fixture
def closed_period(api):
    """A CLOSED period holding the canonical filed pair, which is the state an
    audit needs."""
    return fx.closed_period_with_filings(api)


@pytest.fixture
def approved_plan(api):
    """An approved fiscal-2027 plan of 1000000 cents over a district whose filed
    statements forecast 1164500, giving a funding ratio of 1.1645."""
    ctx = fx.statements_filed(api)
    fx.approved_work_plan(api, ctx)
    return ctx


@pytest.fixture
def running_program(api):
    """A RUNNING 62000-cent program under an approved plan and an EXECUTED DMO
    agreement, with the clock inside the booking window."""
    return fx.running_program(api)
