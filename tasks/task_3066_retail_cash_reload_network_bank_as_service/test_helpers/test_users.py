"""Pre-built role headers for every role in the PRD (PRD §2.1, §2.10).

Three roles are anchored to a persisted entity (BankSponsor, Program,
RetailerAgreement); the other four are opaque operators.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "compliance_analyst_headers": build_user_headers("test-analyst-1", "ComplianceAnalyst"),
    "compliance_officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
    "settlement_operator_headers": build_user_headers("test-settlement-1", "SettlementOperator"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "bank_sponsor_headers": build_user_headers("test-bank-1", "BankSponsor"),
    "program_manager_headers": build_user_headers("test-program-1", "ProgramManager"),
    "retailer_clerk_headers": build_user_headers("test-retailer-1", "RetailerClerk"),
}


# --- Per-instance builders — required for every entity_backed role ---

def make_bank_sponsor_headers(bank_id: str) -> dict:
    """For BankSponsor (entity_backed:BankSponsor). Pass the actual BankSponsor.id
    as user_id whenever the call is ownership-gated (program posture / oversight)."""
    return build_user_headers(bank_id, "BankSponsor")


def make_program_manager_headers(program_id: str) -> dict:
    """For ProgramManager (entity_backed:Program). Pass the actual Program.id as
    user_id whenever the call is ownership-gated (agreement / location state moves)."""
    return build_user_headers(program_id, "ProgramManager")


def make_retailer_clerk_headers(agreement_id: str) -> dict:
    """For RetailerClerk (entity_backed:RetailerAgreement). Pass the actual
    RetailerAgreement.id as user_id whenever the call is ownership-gated
    (load creation/funding, dispute responses)."""
    return build_user_headers(agreement_id, "RetailerClerk")


def make_analyst_headers(operator_id: str) -> dict:
    """Distinct ComplianceAnalyst operator ids for segregation-of-duties checks."""
    return build_user_headers(operator_id, "ComplianceAnalyst")


def make_officer_headers(operator_id: str) -> dict:
    """Distinct ComplianceOfficer operator ids for segregation-of-duties checks."""
    return build_user_headers(operator_id, "ComplianceOfficer")