"""Shared pytest fixtures for the Dog Show Trials API test suite.

The harness restarts the service with an empty database before every individual
test, so no fixture may assume state left behind by another test. Every scenario
builds the rows it needs from scratch through the public API.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import TEST_USERS, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """The shared API client. It holds no per-test state of its own."""
    return api_client


@pytest.fixture
def sanction_officer_headers():
    return TEST_USERS["sanction_officer_headers"]


@pytest.fixture
def sanction_officer_beta_headers():
    return TEST_USERS["sanction_officer_beta_headers"]


@pytest.fixture
def show_secretary_headers():
    return TEST_USERS["show_secretary_headers"]


@pytest.fixture
def registry_officer_headers():
    return TEST_USERS["registry_officer_headers"]


@pytest.fixture
def registry_officer_beta_headers():
    return TEST_USERS["registry_officer_beta_headers"]


@pytest.fixture
def club_officer_headers():
    return TEST_USERS["club_officer_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]


@pytest.fixture
def handler_headers():
    return TEST_USERS["handler_headers"]
