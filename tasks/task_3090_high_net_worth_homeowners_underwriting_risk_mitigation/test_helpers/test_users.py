"""Pre-built role headers for every role the platform recognizes.

`AgencyProducer` is the one entity-backed role: its `X-User-ID` is the `id` of the
acting `Agency`. The shared constant is a fallback for calls that do not exercise
ownership; every ownership-gated call MUST use `make_agency_producer_headers(agency_id)`.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — the shared constant is the canonical form.
    "underwriter_headers": build_user_headers("uw-harper-1", "Underwriter"),
    "claims_adjuster_headers": build_user_headers("adj-morgan", "ClaimsAdjuster"),
    "risk_consultant_headers": build_user_headers("rc-dana", "RiskConsultant"),
    "platform_admin_headers": build_user_headers("ops-root-1", "PlatformAdmin"),
    "compliance_reporter_headers": build_user_headers("cr-quill-1", "ComplianceReporter"),
    # Unauthenticated caller used to exercise the authentication gate.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # entity_backed:Agency — fallback only; use the builder for ownership-gated calls.
    "agency_producer_headers": build_user_headers("test-agency-producer-1", "AgencyProducer"),
}


def make_agency_producer_headers(agency_id: str) -> dict:
    """For AgencyProducer (entity_backed:Agency).

    Pass the actual Agency.id as the user id whenever the call is ownership-gated
    (submit, recall, withdraw, and every producer-scoped write).
    """
    return build_user_headers(agency_id, "AgencyProducer")