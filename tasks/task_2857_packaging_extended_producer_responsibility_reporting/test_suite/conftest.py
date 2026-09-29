"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    REGULATOR_ALT_HEADERS,
    REGULATOR_HEADERS,
    VERIFIER_ALT_HEADERS,
    VERIFIER_HEADERS,
    VERIFIER_THIRD_HEADERS,
    ApiClient,
)


@pytest.fixture
def api() -> ApiClient:
    """A fresh client per test; the runner restarts the server between tests."""
    return ApiClient()


@pytest.fixture
def regulator_headers():
    """ProgramRegulator headers; the identifier is opaque."""
    return REGULATOR_HEADERS


@pytest.fixture
def regulator_alt_headers():
    """A second ProgramRegulator identity."""
    return REGULATOR_ALT_HEADERS


@pytest.fixture
def verifier_headers():
    """IndependentVerifier headers for verifier-001."""
    return VERIFIER_HEADERS


@pytest.fixture
def verifier_alt_headers():
    """IndependentVerifier headers for verifier-002."""
    return VERIFIER_ALT_HEADERS


@pytest.fixture
def verifier_third_headers():
    """IndependentVerifier headers for verifier-003."""
    return VERIFIER_THIRD_HEADERS
