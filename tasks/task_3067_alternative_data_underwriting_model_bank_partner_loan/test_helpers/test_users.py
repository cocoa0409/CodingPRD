"""Pre-built role headers for every role in the PRD.

All roles in this PRD use opaque operator identifiers (X-User-ID is never
compared to any entity's id), so shared constants are the canonical form.
Named constants per operator are still provided for segregation-of-duties
scenarios, where the identity of the acting operator matters.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("pad-one", "PlatformAdmin"),
    "risk_officer_creator_headers": build_user_headers("ro-creator", "RiskOfficer"),
    "risk_officer_validator_headers": build_user_headers("ro-validator", "RiskOfficer"),
    "risk_officer_attester_headers": build_user_headers("ro-attester", "RiskOfficer"),
    "partner_admin_headers": build_user_headers("pa-one", "PartnerAdmin"),
    "partner_admin_two_headers": build_user_headers("pa-two", "PartnerAdmin"),
    "partner_admin_nine_headers": build_user_headers("pa-nine", "PartnerAdmin"),
    "verification_officer_headers": build_user_headers("vo-one", "VerificationOfficer"),
    "verification_officer_two_headers": build_user_headers("vo-two", "VerificationOfficer"),
    "servicing_agent_headers": build_user_headers("sa-one", "ServicingAgent"),
    "collections_agent_headers": build_user_headers("ca-one", "CollectionsAgent"),
    "auditor_headers": build_user_headers("au-one", "Auditor"),
}


def make_platform_admin_headers(user_id: str = "pad-one") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_risk_officer_headers(user_id: str = "ro-creator") -> dict:
    return build_user_headers(user_id, "RiskOfficer")


def make_partner_admin_headers(user_id: str = "pa-one") -> dict:
    return build_user_headers(user_id, "PartnerAdmin")


def make_verification_officer_headers(user_id: str = "vo-one") -> dict:
    return build_user_headers(user_id, "VerificationOfficer")


def make_servicing_agent_headers(user_id: str = "sa-one") -> dict:
    return build_user_headers(user_id, "ServicingAgent")


def make_collections_agent_headers(user_id: str = "ca-one") -> dict:
    return build_user_headers(user_id, "CollectionsAgent")


def make_auditor_headers(user_id: str = "au-one") -> dict:
    return build_user_headers(user_id, "Auditor")
