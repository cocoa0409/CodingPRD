"""Pytest fixtures exposing the destination-sales test infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle belongs to the runner."""
    return api_client


@pytest.fixture
def bureau_admin_headers():
    return TEST_USERS["bureau_admin_headers"]


@pytest.fixture
def sales_manager_headers():
    return TEST_USERS["sales_manager_headers"]


@pytest.fixture
def center_scheduler_headers():
    return TEST_USERS["center_scheduler_headers"]


@pytest.fixture
def incentive_approver_headers():
    return TEST_USERS["incentive_approver_headers"]


@pytest.fixture
def services_manager_headers():
    return TEST_USERS["services_manager_headers"]


@pytest.fixture
def board_analyst_headers():
    return TEST_USERS["board_analyst_headers"]


@pytest.fixture
def hotel_partner_headers():
    """Ownership-neutral HotelPartner headers; ownership-gated calls must use
    make_hotel_partner_headers(hotel_id) instead."""
    return TEST_USERS["hotel_partner_headers"]


@pytest.fixture
def meeting_planner_headers():
    """Ownership-neutral MeetingPlanner headers; ownership-gated calls must use
    make_meeting_planner_headers(planner_id) instead."""
    return TEST_USERS["meeting_planner_headers"]
