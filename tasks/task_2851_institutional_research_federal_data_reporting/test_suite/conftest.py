"""Shared pytest bridge between the test suite and the test_helpers package."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    make_analyst_headers,
    make_director_headers,
    make_disclosure_headers,
    make_registrar_headers,
    make_steward_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """One HTTP client for the whole run; the harness restarts the server per test."""
    return ApiClient()


@pytest.fixture
def analyst():
    """An IRAnalyst who assembles components, publishes figures and files restatements."""
    return make_analyst_headers()


@pytest.fixture
def director():
    """An IRDirector, the approving authority for certification, freeze and restatements."""
    return make_director_headers()


@pytest.fixture
def registrar():
    """A RegistrarOfficer who owns the census snapshot and the student roster."""
    return make_registrar_headers()


@pytest.fixture
def steward():
    """A DataSteward who owns the federal definition library and mapping verdicts."""
    return make_steward_headers()


@pytest.fixture
def disclosure():
    """A DisclosureOfficer, the only role permitted to write disclosure artefacts."""
    return make_disclosure_headers()
