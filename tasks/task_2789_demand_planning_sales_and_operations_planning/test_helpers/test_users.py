"""Pre-built role headers for every role in the PRD.

Five of the six roles carry an opaque operator identifier in ``X-User-ID`` that
is never matched against any row's ``id``, so the shared constants below are the
canonical form for them.  ``CustomerRep`` is different: its ``X-User-ID`` is the
``id`` of the acting ``Customer``, so ownership-gated calls MUST use
``make_customer_rep_headers(customer["id"])`` with the real customer id.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER_ID,
    EXEC_USER_ID,
    LEAD_USER_ID,
    PLANNER_USER_ID,
    SUPPLY_USER_ID,
)

TEST_USERS = {
    "sop_admin_headers": build_user_headers(ADMIN_USER_ID, "SopAdmin"),
    "demand_planner_headers": build_user_headers(PLANNER_USER_ID, "DemandPlanner"),
    "demand_review_lead_headers": build_user_headers(LEAD_USER_ID, "DemandReviewLead"),
    "supply_planner_headers": build_user_headers(SUPPLY_USER_ID, "SupplyPlanner"),
    "executive_sponsor_headers": build_user_headers(EXEC_USER_ID, "ExecutiveSponsor"),
    # CustomerRep is customer-backed: this shared constant is a fallback for
    # tests that do not exercise ownership at all.
    "customer_rep_headers": build_user_headers("customer-rep-unbound", "CustomerRep"),
}


def make_sop_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SopAdmin")


def make_demand_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DemandPlanner")


def make_demand_review_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DemandReviewLead")


def make_supply_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupplyPlanner")


def make_executive_sponsor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ExecutiveSponsor")


def make_customer_rep_headers(customer_id: str) -> dict:
    """For CustomerRep, whose X-User-ID is the id of the acting Customer.
    Pass the real ``Customer.id`` whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "CustomerRep")
