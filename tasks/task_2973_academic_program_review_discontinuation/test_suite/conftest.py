"""Shared pytest fixtures.

The runner owns the server lifecycle and the database is empty before every
single test, so nothing here needs to clean up after itself.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    make_hr_partner_headers,
    make_provost_proposer_headers,
    make_provost_ratifier_headers,
    make_registrar_headers,
    make_review_coordinator_headers,
)


@pytest.fixture
def api():
    """The endpoint client, pointed at the server the runner started."""
    return ApiClient()


@pytest.fixture
def coordinator_headers():
    return make_review_coordinator_headers()


@pytest.fixture
def provost_headers():
    """The proposing provost."""
    return make_provost_proposer_headers()


@pytest.fixture
def ratifier_headers():
    """The second provost, distinct from the proposer."""
    return make_provost_ratifier_headers()


@pytest.fixture
def registrar_headers():
    return make_registrar_headers()


@pytest.fixture
def hr_headers():
    return make_hr_partner_headers()
