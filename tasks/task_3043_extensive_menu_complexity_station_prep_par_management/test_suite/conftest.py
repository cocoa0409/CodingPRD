"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; these tests assume the server is
already running at API_BASE_URL and is restarted (empty database) before
every test.
"""
import pytest

from test_helpers import (
    api_client, ApiClient,
    system_admin_headers, menu_admin_headers, inventory_controller_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server process is managed externally."""
    return api_client


@pytest.fixture
def sysadmin_headers():
    return system_admin_headers()


@pytest.fixture
def menu_admin():
    return menu_admin_headers()


@pytest.fixture
def inventory_controller():
    return inventory_controller_headers()
