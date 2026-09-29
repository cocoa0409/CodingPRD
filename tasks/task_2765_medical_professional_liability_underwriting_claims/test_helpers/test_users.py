"""Pre-built role headers for every role in the PRD.

Seven of the eight roles are carrier-side operator roles whose X-User-ID is an
opaque operator identifier never compared to any entity id. The eighth role,
Insured, carries the id of the acting insured record, so ownership-gated calls
must use make_insured_headers(insured["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import OPERATOR_IDS

# Shared constants — canonical for the seven opaque operator roles.
TEST_USERS = {
    "underwriting_officer_headers": build_user_headers(
        OPERATOR_IDS["UnderwritingOfficer"], "UnderwritingOfficer"
    ),
    "claims_adjuster_headers": build_user_headers(
        OPERATOR_IDS["ClaimsAdjuster"], "ClaimsAdjuster"
    ),
    "claims_adjuster_two_headers": build_user_headers(
        OPERATOR_IDS["ClaimsAdjusterSecond"], "ClaimsAdjuster"
    ),
    "claims_committee_approver_headers": build_user_headers(
        OPERATOR_IDS["ClaimsCommitteeApprover"], "ClaimsCommitteeApprover"
    ),
    "peer_review_chair_headers": build_user_headers(
        OPERATOR_IDS["PeerReviewChair"], "PeerReviewChair"
    ),
    "actuarial_analyst_headers": build_user_headers(
        OPERATOR_IDS["ActuarialAnalyst"], "ActuarialAnalyst"
    ),
    "chief_actuary_headers": build_user_headers(
        OPERATOR_IDS["ChiefActuary"], "ChiefActuary"
    ),
    "compliance_officer_headers": build_user_headers(
        OPERATOR_IDS["ComplianceOfficer"], "ComplianceOfficer"
    ),
    # Fallback only for tests that do not exercise ownership at all.
    "insured_headers": build_user_headers("insured-placeholder", "Insured"),
}

CARRIER_ROLE_NAMES = [
    "UnderwritingOfficer",
    "ClaimsAdjuster",
    "ClaimsCommitteeApprover",
    "PeerReviewChair",
    "ActuarialAnalyst",
    "ChiefActuary",
    "ComplianceOfficer",
]


def make_operator_headers(user_id: str, role: str) -> dict:
    """Headers for any of the seven opaque carrier-side operator roles."""
    return build_user_headers(user_id, role)


def make_insured_headers(insured_id: str) -> dict:
    """For the Insured role, whose X-User-ID is the acting insured's own id.

    Pass the real Insured.id whenever the call is ownership-gated.
    """
    return build_user_headers(insured_id, "Insured")


def make_underwriting_officer_headers(user_id: str = None) -> dict:
    return build_user_headers(user_id or OPERATOR_IDS["UnderwritingOfficer"],
                              "UnderwritingOfficer")


def make_claims_adjuster_headers(user_id: str = None) -> dict:
    return build_user_headers(user_id or OPERATOR_IDS["ClaimsAdjuster"],
                              "ClaimsAdjuster")


def make_claims_committee_approver_headers(user_id: str = None) -> dict:
    return build_user_headers(user_id or OPERATOR_IDS["ClaimsCommitteeApprover"],
                              "ClaimsCommitteeApprover")


def make_peer_review_chair_headers(user_id: str = None) -> dict:
    return build_user_headers(user_id or OPERATOR_IDS["PeerReviewChair"],
                              "PeerReviewChair")


def make_actuarial_analyst_headers(user_id: str = None) -> dict:
    return build_user_headers(user_id or OPERATOR_IDS["ActuarialAnalyst"],
                              "ActuarialAnalyst")


def make_chief_actuary_headers(user_id: str = None) -> dict:
    return build_user_headers(user_id or OPERATOR_IDS["ChiefActuary"],
                              "ChiefActuary")


def make_compliance_officer_headers(user_id: str = None) -> dict:
    return build_user_headers(user_id or OPERATOR_IDS["ComplianceOfficer"],
                              "ComplianceOfficer")
