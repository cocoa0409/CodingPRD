"""Pre-built role headers for every role in the PRD (PRD §2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
# Six of the seven roles carry an opaque X-User-ID; Client carries a Household.id.
TEST_USERS = {
    "admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "advisor_ops_headers": build_user_headers("test-advisor-ops-1", "AdvisorOperationsLead"),
    "support_analyst_headers": build_user_headers("test-support-analyst-1", "AdvisorSupportAnalyst"),
    "custody_officer_headers": build_user_headers("test-custody-officer-1", "CustodyOperationsOfficer"),
    "compliance_headers": build_user_headers("test-compliance-reviewer-1", "ComplianceReviewer"),
    "committee_chair_headers": build_user_headers("test-committee-chair-1", "InvestmentCommitteeChair"),
    # Client is entity_backed:Household — the shared constant is only a fallback for
    # tests that never reach an ownership check.
    "client_headers": build_user_headers("test-client-household-1", "Client"),
}


# Per-instance builders — required for every entity_backed role.
def make_client_headers(user_id: str) -> dict:
    """For Client, X-User-ID is the acting Household.id. Pass the actual
    Household id whenever the call is ownership-gated (which is every
    Client call in this domain)."""
    return build_user_headers(user_id, "Client")


def make_compliance_headers(user_id: str) -> dict:
    """Opaque reviewer identity; distinct identities drive the segregation-of-duties
    comparisons that compare X-User-ID against a row's recorded drafter."""
    return build_user_headers(user_id, "ComplianceReviewer")


def make_advisor_ops_headers(user_id: str) -> dict:
    """Opaque operator-lead identity; used where the recorded actor matters."""
    return build_user_headers(user_id, "AdvisorOperationsLead")


def make_custody_officer_headers(user_id: str) -> dict:
    """Opaque custodian-officer identity; used where the recorded actor matters."""
    return build_user_headers(user_id, "CustodyOperationsOfficer")