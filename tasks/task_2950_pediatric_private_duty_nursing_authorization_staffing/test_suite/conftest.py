"""Pytest configuration for the Pediatric PDN Authorization Staffing suite.

The server lifecycle, the base URL and result collection belong to the runner.
This module only puts the task root on ``sys.path`` and exposes the two shared
fixtures every test file uses.
"""

import os
import sys

import pytest

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers import ApiClient  # noqa: E402
from test_helpers.fixtures import Baseline, setup_baseline  # noqa: E402,F401


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the freshly restarted server for this test."""
    return ApiClient()


@pytest.fixture
def baseline(api: ApiClient) -> Baseline:
    """The canonical chain: clock parked in ISO week 32 of 2026, payer, patient,
    submitted plan of care, ACTIVE 40 h/wk authorization, a TRACH+VENT nurse and
    an ACTIVE case naming that nurse for continuity."""
    return setup_baseline(api)
