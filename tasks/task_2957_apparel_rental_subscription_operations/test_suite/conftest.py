"""Shared pytest fixtures for the apparel rental subscription suite.

The service is restarted with an empty database before every test, so no
fixture here may be broader than function scope for anything that touches
server state: each test provisions the whole world it needs from scratch.
"""

from __future__ import annotations

import os
import sys

import pytest

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.api_client import ApparelRentalClient  # noqa: E402
from test_helpers.fixtures import Scenario  # noqa: E402


@pytest.fixture()
def client() -> ApparelRentalClient:
    """The typed HTTP surface, pointed at the server under test."""
    return ApparelRentalClient()


@pytest.fixture()
def scenario(client: ApparelRentalClient) -> Scenario:
    """A fresh scenario builder over an empty database."""
    return Scenario(client)
