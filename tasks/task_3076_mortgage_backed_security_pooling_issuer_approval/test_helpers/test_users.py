"""Pre-built role headers for every role in the PRD.

ApplicantOfficer, AgencyReviewer and PlatformAdmin use opaque operator ids,
so shared constants are canonical for them. IssuerOfficer is entity-backed by
Issuer (X-User-ID is the Issuer's id) and DocumentCustodian is entity-backed
by DocumentCustodian — for those, always use the per-instance builders with
the real entity id whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "applicant_officer_headers": build_user_headers("applicant-officer-1", "ApplicantOfficer"),
    "agency_reviewer_headers": build_user_headers("reviewer-1", "AgencyReviewer"),
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    # Entity-backed roles — fallback constants for non-ownership tests ONLY.
    "issuer_officer_headers": build_user_headers("issuer-officer-fallback", "IssuerOfficer"),
    "document_custodian_headers": build_user_headers("custodian-fallback", "DocumentCustodian"),
}


def make_applicant_officer_headers(user_id: str) -> dict:
    """ApplicantOfficer with an explicit opaque user id (used to control the
    segregation-of-duties identity at application submit)."""
    return build_user_headers(user_id, "ApplicantOfficer")


def make_agency_reviewer_headers(user_id: str) -> dict:
    """AgencyReviewer with an explicit opaque user id (used to control the
    segregation-of-duties identity at application approve/deny)."""
    return build_user_headers(user_id, "AgencyReviewer")


def make_issuer_officer_headers(issuer_id: str) -> dict:
    """IssuerOfficer is entity-backed by Issuer: X-User-ID must equal the
    Issuer's id for any ownership-gated call."""
    return build_user_headers(issuer_id, "IssuerOfficer")


def make_document_custodian_headers(custodian_id: str) -> dict:
    """DocumentCustodian is entity-backed by DocumentCustodian: X-User-ID
    must equal the DocumentCustodian's id when certifying."""
    return build_user_headers(custodian_id, "DocumentCustodian")


def make_platform_admin_headers(user_id: str = "platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
