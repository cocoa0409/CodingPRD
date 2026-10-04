"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle, API_BASE_URL injection, and PYTHONPATH;
these fixtures are a thin bridge over the generated helpers.
"""
from datetime import datetime, timezone

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner
    (per-test restart); this client only knows how to speak HTTP to it."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def merch_headers():
    """OriginationMerchandiser (opaque role)."""
    return TEST_USERS["origination_merchandiser_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["plant_scheduler_headers"]


@pytest.fixture
def product_merch_headers():
    return TEST_USERS["product_merchandiser_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["sustainability_auditor_headers"]


@pytest.fixture
def trader_headers():
    return TEST_USERS["crush_trader_headers"]


@pytest.fixture
def risk_headers():
    return TEST_USERS["risk_manager_headers"]


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime so tests compare
    instants, not string spellings (the PRD pins instants, not a rendering)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )
