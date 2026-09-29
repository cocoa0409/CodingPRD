"""Pre-built role headers for the eight roles the PRD declares.

Six roles carry an opaque operator identity; the shared constants below are the
canonical form for them.  ``HotelPartner`` and ``MeetingPlanner`` are
entity-backed: their ``X-User-ID`` must be the id of the acting ``Hotel`` or
``MeetingPlanner`` row, so ownership-gated calls MUST use the per-instance
builders ``make_hotel_partner_headers`` / ``make_meeting_planner_headers``.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Distinct opaque operator identifiers -- never reuse one across two officers
# whose identities the PRD requires to differ (segregation of duties).
BUREAU_ADMIN_USER_ID = "admin-01"
SALES_MANAGER_USER_ID = "sales-01"
SALES_MANAGER_2_USER_ID = "sales-02"
CENTER_SCHEDULER_USER_ID = "scheduler-01"
INCENTIVE_APPROVER_USER_ID = "approver-01"
INCENTIVE_APPROVER_2_USER_ID = "approver-02"
SERVICES_MANAGER_USER_ID = "services-01"
BOARD_ANALYST_USER_ID = "analyst-01"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "bureau_admin_headers": build_user_headers(BUREAU_ADMIN_USER_ID, "BureauAdmin"),
    "sales_manager_headers": build_user_headers(SALES_MANAGER_USER_ID, "SalesManager"),
    "sales_manager_2_headers": build_user_headers(SALES_MANAGER_2_USER_ID, "SalesManager"),
    "center_scheduler_headers": build_user_headers(CENTER_SCHEDULER_USER_ID, "CenterScheduler"),
    "incentive_approver_headers": build_user_headers(INCENTIVE_APPROVER_USER_ID, "IncentiveApprover"),
    "incentive_approver_2_headers": build_user_headers(INCENTIVE_APPROVER_2_USER_ID, "IncentiveApprover"),
    "services_manager_headers": build_user_headers(SERVICES_MANAGER_USER_ID, "ServicesManager"),
    "board_analyst_headers": build_user_headers(BOARD_ANALYST_USER_ID, "BoardAnalyst"),
    # Fallbacks for the two entity-backed roles -- valid only where the call
    # under test performs no ownership comparison (401/403/404/400 probes).
    "hotel_partner_headers": build_user_headers("hotel-partner-unowned", "HotelPartner"),
    "meeting_planner_headers": build_user_headers("planner-unowned", "MeetingPlanner"),
}

ROLE_HEADER_KEYS = {
    "BureauAdmin": "bureau_admin_headers",
    "SalesManager": "sales_manager_headers",
    "CenterScheduler": "center_scheduler_headers",
    "IncentiveApprover": "incentive_approver_headers",
    "ServicesManager": "services_manager_headers",
    "BoardAnalyst": "board_analyst_headers",
    "HotelPartner": "hotel_partner_headers",
    "MeetingPlanner": "meeting_planner_headers",
}


def headers_for_role(role: str) -> Dict[str, str]:
    """Shared headers for a role name; ownership-neutral call sites only."""
    return TEST_USERS[ROLE_HEADER_KEYS[role]]


def make_hotel_partner_headers(hotel_id: str) -> Dict[str, str]:
    """HotelPartner acts as a Hotel row: pass the actual Hotel.id."""
    return build_user_headers(hotel_id, "HotelPartner")


def make_meeting_planner_headers(planner_id: str) -> Dict[str, str]:
    """MeetingPlanner acts as a MeetingPlanner row: pass the actual planner id."""
    return build_user_headers(planner_id, "MeetingPlanner")


def make_sales_manager_headers(user_id: str) -> Dict[str, str]:
    """SalesManager with a pinned operator id (segregation-of-duties tests)."""
    return build_user_headers(user_id, "SalesManager")


def make_incentive_approver_headers(user_id: str) -> Dict[str, str]:
    """IncentiveApprover with a pinned operator id (segregation-of-duties tests)."""
    return build_user_headers(user_id, "IncentiveApprover")


def headers_without_user_id(role: str = "BureauAdmin") -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = BUREAU_ADMIN_USER_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_blank_user_id(role: str = "BureauAdmin") -> Dict[str, str]:
    # A PRD-"blank" header is the empty string; a whitespace value would be
    # rejected client-side and never reach the server.
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_blank_role(user_id: str = BUREAU_ADMIN_USER_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_with_undeclared_role(user_id: str = BUREAU_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "DestinationOverlord")
