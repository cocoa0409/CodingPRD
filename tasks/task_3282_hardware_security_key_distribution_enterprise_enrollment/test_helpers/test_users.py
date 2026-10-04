"""Pre-built role headers for every role in the PRD.

Employee is the entity-backed role: X-User-ID must equal the Employee.id of
the acting employee for ownership-gated calls (temporary-access use).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("pa1", "PlatformAdmin"),
    "security_admin_headers": build_user_headers("seca1", "SecurityAdmin"),
    "security_admin_2_headers": build_user_headers("seca2", "SecurityAdmin"),
    "procurement_admin_headers": build_user_headers("proca1", "ProcurementAdmin"),
    "logistics_coordinator_headers": build_user_headers("logc1", "LogisticsCoordinator"),
    "helpdesk_agent_headers": build_user_headers("hd1", "HelpDeskAgent"),
    "helpdesk_agent_2_headers": build_user_headers("hd2", "HelpDeskAgent"),
    # Fallback only for non-ownership tests; use make_employee_headers for real use.
    "employee_headers": build_user_headers("emp-shared", "Employee"),
}


def make_employee_headers(employee_id: str) -> dict:
    """For Employee (entity_backed:Employee). Pass the actual Employee.id as
    employee_id whenever the call is ownership-gated (grant use)."""
    return build_user_headers(employee_id, "Employee")


def make_security_admin_headers(user_id: str) -> dict:
    """SecurityAdmin with a chosen X-User-ID (for segregation-of-duties tests)."""
    return build_user_headers(user_id, "SecurityAdmin")


def make_helpdesk_agent_headers(user_id: str) -> dict:
    """HelpDeskAgent with a chosen X-User-ID (for segregation-of-duties tests)."""
    return build_user_headers(user_id, "HelpDeskAgent")


def make_procurement_admin_headers(user_id: str) -> dict:
    """ProcurementAdmin with a chosen X-User-ID."""
    return build_user_headers(user_id, "ProcurementAdmin")
