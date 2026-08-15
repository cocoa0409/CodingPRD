"""Pre-built role headers for every role in the PRD (section 2.1).

All roles in this PRD use opaque operator identifiers: ``X-User-ID`` is not
tied to any persisted entity, but it is recorded on produced artifacts and
compared by the segregation-of-duties checks (PRD section 2.11). The shared
constants below are canonical for plain role-gated calls; the per-instance
builders are used whenever a scenario needs two operators of the same role
with distinct identifiers (for example weld operator vs weld certifier).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "assembly_lead_headers": build_user_headers("al-1", "AssemblyLead"),
    "quality_engineer_headers": build_user_headers("qe-1", "QualityEngineer"),
    "safety_officer_headers": build_user_headers("so-1", "SafetyOfficer"),
    "logistics_coordinator_headers": build_user_headers("lc-1", "LogisticsCoordinator"),
    "carrier_agent_headers": build_user_headers("ca-1", "CarrierAgent"),
    "customer_service_headers": build_user_headers("cs-1", "CustomerService"),
    "any_headers": build_user_headers("reader-1", "Any"),
}


def make_assembly_lead_headers(user_id: str) -> dict:
    """AssemblyLead headers with a specific operator id (recorded as
    operator_id / flashed_by_id and bound as firmware submitter)."""
    return build_user_headers(user_id, "AssemblyLead")


def make_quality_engineer_headers(user_id: str) -> dict:
    """QualityEngineer headers with a specific operator id (recorded as
    inspector_id / certified_by_id)."""
    return build_user_headers(user_id, "QualityEngineer")


def make_safety_officer_headers(user_id: str) -> dict:
    """SafetyOfficer headers with a specific operator id (recorded as
    approver_id / approved_by_id)."""
    return build_user_headers(user_id, "SafetyOfficer")


def make_logistics_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LogisticsCoordinator")


def make_carrier_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CarrierAgent")


def make_customer_service_headers(user_id: str) -> dict:
    """CustomerService headers with a specific operator id (recorded as
    requested_by_id on a ReturnAuthorization)."""
    return build_user_headers(user_id, "CustomerService")


def make_any_headers(user_id: str = "reader-1") -> dict:
    return build_user_headers(user_id, "Any")
