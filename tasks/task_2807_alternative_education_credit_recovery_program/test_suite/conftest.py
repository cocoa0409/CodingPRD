"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ALT_ED_TEACHER_HEADERS,
    DISTRICT_ADMIN_ALT_HEADERS,
    DISTRICT_ADMIN_HEADERS,
    EMPTY_USER_ID_HEADERS,
    NO_AUTH_HEADERS,
    REGISTRAR_ALT_HEADERS,
    REGISTRAR_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def district_admin_headers():
    """The district office operator who opens centres and drives the clock."""
    return DISTRICT_ADMIN_HEADERS


@pytest.fixture
def second_district_admin_headers():
    """A second district operator, for the paired re-entry approval."""
    return DISTRICT_ADMIN_ALT_HEADERS


@pytest.fixture
def registrar_headers():
    """The transcript owner who posts historical rows and plans."""
    return REGISTRAR_HEADERS


@pytest.fixture
def second_registrar_headers():
    """A second registrar, for the paired credit award."""
    return REGISTRAR_ALT_HEADERS


@pytest.fixture
def alt_ed_teacher_headers():
    """On-site instructional staff."""
    return ALT_ED_TEACHER_HEADERS


@pytest.fixture
def unauthenticated_headers():
    """Headers carrying neither identity header."""
    return NO_AUTH_HEADERS


@pytest.fixture
def empty_user_id_headers():
    """Headers carrying a role but an empty acting user identifier."""
    return EMPTY_USER_ID_HEADERS
