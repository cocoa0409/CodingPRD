"""Pytest wiring for the otolaryngology practice test suite.

The harness relaunches the API server before every individual test, so each test
below opens on an empty database with the logical clock reading exactly
2026-08-01T00:00:00Z. Every entity a test needs is therefore built inside that
test through declared endpoints.
"""

import os
import sys

import pytest

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers import ApiClient, ApiErrorId  # noqa: E402
from test_helpers import assertions as asserts  # noqa: E402
from test_helpers import constants as C  # noqa: E402
from test_helpers import factories as F  # noqa: E402
from test_helpers import fixtures as SETUP  # noqa: E402
from test_helpers import test_users as USERS  # noqa: E402


@pytest.fixture
def api():
    """A client bound to the server the harness started for this test."""
    return ApiClient()


@pytest.fixture
def errors():
    """The error-identifier catalogue."""
    return ApiErrorId


@pytest.fixture
def users():
    """Pre-built identity headers for every acting role."""
    return USERS


@pytest.fixture
def setup():
    """Composite setup helpers, each building its entities over the API."""
    return SETUP


@pytest.fixture
def domain():
    """Domain constants: enum members, thresholds and default plan terms."""
    return C


@pytest.fixture
def payloads():
    """Request-payload builders."""
    return F


@pytest.fixture
def check():
    """Shape, format and invariant assertions."""
    return asserts
