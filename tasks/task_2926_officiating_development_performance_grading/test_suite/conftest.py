"""Shared pytest wiring for the Officiating Development & Grading test suite.

The harness restarts the service before every individual test, so every test
starts against an empty database and each fixture builds its preconditions from
scratch. Nothing here is session-scoped.
"""
import os
import sys

import pytest

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.api_client import api_client as _api_client  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    READER_HEADERS_BY_ROLE,
    TEST_USERS,
)


@pytest.fixture
def api():
    """The endpoint client."""
    return _api_client


@pytest.fixture
def users():
    """Header sets keyed by role, for tests that need several callers."""
    return TEST_USERS


@pytest.fixture
def readers():
    """One reader identity per declared role name."""
    return READER_HEADERS_BY_ROLE


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def grader_headers():
    return TEST_USERS["grader_headers"]


@pytest.fixture
def appeal_reviewer_headers():
    return TEST_USERS["appeal_reviewer_headers"]


@pytest.fixture
def field_evaluator_headers():
    return TEST_USERS["field_evaluator_headers"]


@pytest.fixture
def replay_official_headers():
    return TEST_USERS["replay_official_headers"]


@pytest.fixture
def training_coordinator_headers():
    return TEST_USERS["training_coordinator_headers"]


@pytest.fixture
def communications_headers():
    return TEST_USERS["communications_headers"]
