"""Shared pytest fixtures.

The runner relaunches the server before every individual test, so every fixture
here builds its world from an empty database through the public API only.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: F401,E402  (registers the §5 status map)
from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.fixtures import (  # noqa: E402
    setup_aurora_drift,
    setup_registry,
    setup_single_alpha,
    setup_single_gold,
    setup_twinpeak,
)
from test_helpers.test_users import ADMIN_HEADERS  # noqa: E402


@pytest.fixture
def api():
    return ApiClient()


@pytest.fixture
def admin_headers():
    return ADMIN_HEADERS


@pytest.fixture
def registry(api):
    return setup_registry(api)


@pytest.fixture
def aurora_drift(api):
    return setup_aurora_drift(api)


@pytest.fixture
def single_alpha(api):
    return setup_single_alpha(api)


@pytest.fixture
def twinpeak(api):
    return setup_twinpeak(api)


@pytest.fixture
def single_gold(api):
    return setup_single_gold(api)
