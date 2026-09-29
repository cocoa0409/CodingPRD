"""Pre-built role headers for every role in the PRD.

A FintechPartner's X-User-ID is the id of the Partner row it represents, so
FintechPartner calls must always be built per instance with
make_fintech_partner_headers(partner["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Distinct user ids per role so that segregation-of-duties tests can pick a
# second actor of the same role who did not originate the record.
PROGRAM_OFFICER_1 = "po_1"
PROGRAM_OFFICER_2 = "po_2"
COMPLIANCE_OFFICER_1 = "co_1"
COMPLIANCE_OFFICER_2 = "co_2"
RISK_COMMITTEE_1 = "rc_1"
RISK_COMMITTEE_2 = "rc_2"
INTERNAL_AUDIT_1 = "ia_1"

TEST_USERS = {
    "program_officer_headers": build_user_headers(PROGRAM_OFFICER_1, "ProgramOfficer"),
    "program_officer_2_headers": build_user_headers(PROGRAM_OFFICER_2, "ProgramOfficer"),
    "compliance_officer_headers": build_user_headers(COMPLIANCE_OFFICER_1, "ComplianceOfficer"),
    "compliance_officer_2_headers": build_user_headers(COMPLIANCE_OFFICER_2, "ComplianceOfficer"),
    "risk_committee_headers": build_user_headers(RISK_COMMITTEE_1, "RiskCommittee"),
    "risk_committee_2_headers": build_user_headers(RISK_COMMITTEE_2, "RiskCommittee"),
    "internal_audit_headers": build_user_headers(INTERNAL_AUDIT_1, "InternalAudit"),
    # Fallback only: never use for a partner-scoped call.
    "fintech_partner_headers": build_user_headers("fp_unbound", "FintechPartner"),
}


def make_program_officer_headers(user_id: str = PROGRAM_OFFICER_1) -> dict:
    return build_user_headers(user_id, "ProgramOfficer")


def make_compliance_officer_headers(user_id: str = COMPLIANCE_OFFICER_1) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_risk_committee_headers(user_id: str = RISK_COMMITTEE_1) -> dict:
    return build_user_headers(user_id, "RiskCommittee")


def make_internal_audit_headers(user_id: str = INTERNAL_AUDIT_1) -> dict:
    return build_user_headers(user_id, "InternalAudit")


def make_fintech_partner_headers(partner_id: str) -> dict:
    """A FintechPartner caller's X-User-ID is the Partner's own id."""
    return build_user_headers(partner_id, "FintechPartner")


ALL_ROLES = [
    "ProgramOfficer",
    "ComplianceOfficer",
    "RiskCommittee",
    "InternalAudit",
    "FintechPartner",
]
