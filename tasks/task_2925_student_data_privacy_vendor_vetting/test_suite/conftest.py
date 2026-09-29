"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    TELEMETRY_HEADERS,
    ApiClient,
    make_blank_identity_headers,
    make_missing_identity_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return ApiClient()


@pytest.fixture
def admin_headers():
    """PrivacyOfficeAdmin identity; the identifier is opaque."""
    return dict(ADMIN_HEADERS)


@pytest.fixture
def telemetry_headers():
    """TelemetryAgent identity; the identifier is opaque."""
    return dict(TELEMETRY_HEADERS)


@pytest.fixture
def blank_identity_headers():
    """Both identity headers present and empty."""
    return make_blank_identity_headers()


@pytest.fixture
def missing_identity_headers():
    """Neither identity header sent."""
    return make_missing_identity_headers()
