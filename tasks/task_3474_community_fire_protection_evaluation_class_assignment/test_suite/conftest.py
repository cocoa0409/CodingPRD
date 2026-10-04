"""Pytest fixtures exposing the test_helpers infrastructure.

The runner normally puts the task root on PYTHONPATH; the sys.path insert
below makes the suite self-sufficient when pytest is invoked directly from
the task directory. The API client is session-scoped: server lifecycle is
owned by the runner, and the client holds no per-test state.
"""
import os
import sys

import pytest

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers import ApiClient, TEST_USERS, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server is managed externally."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["evaluation_coordinator_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["field_analyst_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["class_registrar_headers"]


@pytest.fixture
def comms_supervisor_headers():
    return TEST_USERS["comms_supervisor_headers"]


@pytest.fixture
def insurer_headers():
    return TEST_USERS["insurer_headers"]
