"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants are safe for opaque roles (PlatformAdmin, RegionalManager)
and for tests that do not exercise entity-backed ownership. For entity-backed
roles (StandOperator, ShiftLead, CrewMember, LoyaltyCustomer) ownership-gated
calls MUST use the make_*_headers builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles — canonical shared form
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
    "regional_manager_headers": build_user_headers("rm-1", "RegionalManager"),
    # entity-backed roles — fallback for non-ownership tests only
    "stand_operator_headers": build_user_headers("test-stand-operator-1", "StandOperator"),
    "shift_lead_headers": build_user_headers("test-shift-lead-1", "ShiftLead"),
    "crew_member_headers": build_user_headers("test-crew-member-1", "CrewMember"),
    "loyalty_customer_headers": build_user_headers("test-loyalty-customer-1", "LoyaltyCustomer"),
}


def make_stand_operator_headers(user_id: str) -> dict:
    """StandOperator is entity-backed by CrewMember: pass the acting crew
    member's id (e.g. the agreement's crew_member_id for activation)."""
    return build_user_headers(user_id, "StandOperator")


def make_shift_lead_headers(user_id: str) -> dict:
    """ShiftLead is entity-backed by CrewMember: pass the acting crew member's
    id (e.g. the refund initiator id for segregation-of-duties checks)."""
    return build_user_headers(user_id, "ShiftLead")


def make_crew_member_headers(user_id: str) -> dict:
    """CrewMember is entity-backed by CrewMember: pass the acting crew member's
    id (e.g. the assignment's crew_member_id for check-in)."""
    return build_user_headers(user_id, "CrewMember")


def make_loyalty_customer_headers(user_id: str) -> dict:
    """LoyaltyCustomer is entity-backed by LoyaltyAccount: pass the account id
    (orders/merges/authorizes are ownership-gated on loyalty_account_id)."""
    return build_user_headers(user_id, "LoyaltyCustomer")
