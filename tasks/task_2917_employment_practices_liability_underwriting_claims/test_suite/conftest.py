"""Shared pytest fixtures for the EPLI compliance suite.

The runner restarts the service with an empty database before every individual
test, so every fixture below builds its state from scratch through the public
API.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import fixtures as S  # noqa: E402
from test_helpers.api_client import ApiClient  # noqa: E402


@pytest.fixture()
def api():
    """Client bound to the service under test."""
    return ApiClient()


@pytest.fixture()
def book(api):
    """CA + TX jurisdictions and one ACTIVE rate plan."""
    return S.carrier_book(api)


@pytest.fixture()
def applicant(api, book):
    """The standard 400-employee CA/TX applicant on the standard book."""
    data = S.create_applicant(api)
    return {"book": book, "plan_id": book["plan_id"], "applicant": data, "applicant_id": data["id"]}


@pytest.fixture()
def world(api):
    """Jurisdictions, ACTIVE plan, applicant, approved assessment and a bound policy."""
    return S.underwritten_policy(api)


@pytest.fixture()
def defense_world(api):
    """``world`` plus a panel firm, an accepted claim and an ACTIVE assignment."""
    return S.defended_claim(api)
