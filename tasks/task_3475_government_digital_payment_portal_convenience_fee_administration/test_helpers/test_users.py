"""Pre-built role headers for every role in the PRD.

Five roles are opaque: their ``X-User-ID`` is never compared to any entity's
``id``, so shared constants are canonical for them. The ``Payer`` role is
entity-backed: its ``X-User-ID`` IS the ``Payer.id``, so any ownership-gated
call MUST use ``make_payer_headers(payer["id"])`` — the shared
``payer_headers`` constant is a fallback for non-ownership tests only.

Three AgencyAdmin ids exist so segregation-of-duties tests can initiate with
one staff user and decide with another.
"""
from prd_bench_local_runner.testing import build_user_headers

PLATFORM_ADMIN_1 = "pa_1"
TREASURY_OFFICER_1 = "to_1"
COMPLIANCE_AUDITOR_1 = "ca_1"
AGENCY_ADMIN_LEAD = "aa-lead"
AGENCY_ADMIN_PEER = "aa-peer"
AGENCY_ADMIN_COUNTY = "aa-county"
ANONYMOUS_1 = "anon_1"

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_1, "PlatformAdmin"),
    "treasury_officer_headers": build_user_headers(TREASURY_OFFICER_1, "TreasuryOfficer"),
    "compliance_auditor_headers": build_user_headers(COMPLIANCE_AUDITOR_1, "ComplianceAuditor"),
    "agency_admin_headers": build_user_headers(AGENCY_ADMIN_LEAD, "AgencyAdmin"),
    "agency_admin_peer_headers": build_user_headers(AGENCY_ADMIN_PEER, "AgencyAdmin"),
    "agency_admin_county_headers": build_user_headers(AGENCY_ADMIN_COUNTY, "AgencyAdmin"),
    "anonymous_headers": build_user_headers(ANONYMOUS_1, "Anonymous"),
    # entity_backed:Payer — FALLBACK ONLY. Never use for a payer-scoped call;
    # this id never equals any real Payer.id, so ownership checks would reject
    # every request. Use make_payer_headers(payer["id"]) instead.
    "payer_headers": build_user_headers("payer_unbound", "Payer"),
}


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_1) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_agency_admin_headers(user_id: str = AGENCY_ADMIN_LEAD) -> dict:
    """AgencyAdmin identity is opaque; pass any staff id. Refund segregation
    compares this id against the refund's initiated_by_user_id."""
    return build_user_headers(user_id, "AgencyAdmin")


def make_treasury_officer_headers(user_id: str = TREASURY_OFFICER_1) -> dict:
    return build_user_headers(user_id, "TreasuryOfficer")


def make_compliance_auditor_headers(user_id: str = COMPLIANCE_AUDITOR_1) -> dict:
    return build_user_headers(user_id, "ComplianceAuditor")


def make_payer_headers(user_id: str) -> dict:
    """For Payer (entity-backed): pass the actual Payer.id as user_id whenever
    the call is ownership-gated — quotes, instruments, transactions, and the
    payer record itself."""
    return build_user_headers(user_id, "Payer")


def make_anonymous_headers(user_id: str = ANONYMOUS_1) -> dict:
    return build_user_headers(user_id, "Anonymous")
