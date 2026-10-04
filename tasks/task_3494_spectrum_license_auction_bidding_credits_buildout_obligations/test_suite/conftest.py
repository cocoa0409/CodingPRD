"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests assume the server is
already running and reachable at API_BASE_URL. Each test starts against an
empty database and the logical clock at its startup default
(2026-09-01T00:00:00Z) — fixtures build every precondition from scratch.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def auction_admin_headers():
    """AuctionAdmin (opaque identity): band planning, auction lifecycle,
    rounds, qualification review, milestone review, incumbent registration
    and relocation scheduling, and the clock endpoint."""
    return TEST_USERS["auction_admin_headers"]


@pytest.fixture
def transfer_reviewer_headers():
    """TransferReviewer (opaque identity): transfer and renewal adjudication.
    Deliberately disjoint from AuctionAdmin (segregation of duties)."""
    return TEST_USERS["transfer_reviewer_headers"]


@pytest.fixture
def bidder_headers():
    """Bootstrap Bidder headers — for self-registration (POST /applicants)
    and non-ownership calls ONLY. Ownership-gated calls must build headers
    from the real applicant id via test_helpers.make_bidder_headers."""
    return TEST_USERS["bidder_headers"]


@pytest.fixture
def incumbent_operator_headers():
    """Bootstrap IncumbentOperator headers — for non-ownership calls ONLY.
    Transition calls must use
    test_helpers.make_incumbent_operator_headers(incumbent["id"])."""
    return TEST_USERS["incumbent_operator_headers"]
