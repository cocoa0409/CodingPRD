"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def operator_headers():
    """A `NetworkOperator` caller; its `X-User-ID` is opaque and never looked up."""
    return TEST_USERS["operator_headers"]


@pytest.fixture
def analyst_headers():
    """A `DisputeAnalyst` caller; its `X-User-ID` is opaque and never looked up."""
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def unknown_member_headers():
    """A `Member` caller whose `X-User-ID` matches no existing member row."""
    return TEST_USERS["unknown_member_headers"]


@pytest.fixture
def unknown_resort_manager_headers():
    """A `ResortManager` caller whose `X-User-ID` matches no existing resort row."""
    return TEST_USERS["unknown_resort_manager_headers"]
