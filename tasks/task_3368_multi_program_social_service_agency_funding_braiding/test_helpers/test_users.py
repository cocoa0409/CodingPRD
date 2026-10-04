"""Pre-built role headers for every role in the PRD.

`X-User-ID` is an opaque operator identifier for every staff role and the
persisted `Client.id` for the `Client` role, so ownership-gated reads by a
client must thread the real entity id through `make_client_headers`.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "intake_specialist_headers": build_user_headers("test-intake-1", "IntakeSpecialist"),
    "program_manager_headers": build_user_headers("test-program-1", "ProgramManager"),
    "finance_officer_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "platform_admin_headers": build_user_headers("test-platform-1", "PlatformAdmin"),
    # Client is entity_backed: this shared constant is a fallback for
    # non-ownership checks only; ownership-gated reads must use the builder.
    "client_headers": build_user_headers("test-client-1", "Client"),
}

# A declared role value that is not one of the six declared roles.
UNDECLARED_ROLE = "Auditor"


def make_client_headers(client_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id as user_id
    whenever the call is ownership-gated (reading the client's own record)."""
    return build_user_headers(client_id, "Client")


def make_intake_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeSpecialist")


def make_program_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramManager")


def make_finance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
