"""Error reporting and role-based access control.

Entity-specific references that do not resolve produce their own 404, and an
acting role that is not permitted for an operation is refused before any
ownership comparison can run.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, TEST_USERS,
    ApiErrorId, make_employer_headers, make_seeker_headers, set_clock,
    create_employer, create_seeker, create_posting, create_active_campaign,
    create_sponsored_job, create_completed_application,
)

ADMIN = TEST_USERS["admin_headers"]
TRUST = TEST_USERS["trust_headers"]


def test_pacing_hold_on_unknown_sponsored_job_reports_not_found(api):
    """PRD §2.8: "3. **Referential existence.** Every resource identifier
    appearing in the request ... must resolve to an existing row. ... the first
    unresolvable identifier determines the error: ... `ERR_SPONSORED_JOB_NOT_FOUND`
    ... all HTTP 404."

    Design: Corner/errors/pacing_hold_on_unknown_sponsored_job_returns_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Missing SJ Co", domain="msj.example")

    res = api.create_pacing_hold(
        "00000000-0000-4000-8000-000000000000",
        {"amount_cents": 100},
        make_employer_headers(employer["id"]))

    validate_error(res, ApiErrorId.ERR_SPONSORED_JOB_NOT_FOUND.value, expected_status=404)


def test_event_missing_the_expected_version_is_refused(api):
    """PRD §2.9: "If the field is absent, the request fails with
    `ERR_MISSING_EXPECTED_VERSION` (HTTP 400)."

    Design: Corner/errors/event_missing_expected_version_returns_400
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Occ Co", domain="occ.example")
    posting = create_posting(employer, title="Occ Engineer")
    campaign = create_active_campaign(employer, name="OC")
    sponsored_job = create_sponsored_job(campaign, posting, employer)

    res = api.record_event({
        "campaign_id": campaign["id"],
        "sponsored_job_id": sponsored_job["id"],
        "event_type": "CLICK",
        "device_fingerprint": "fp-occ-1",
        "ip_hash": "ip-occ-1",
    }, ADMIN)

    validate_error(res, ApiErrorId.ERR_MISSING_EXPECTED_VERSION.value, expected_status=400)


def test_trust_reviewer_cannot_create_a_campaign(api):
    """PRD §2.1: "Operations are gated by role, and an attempt to invoke an
    operation from a role that is not authorized for it is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.1: "The same is true of `TrustReviewer`: `X-User-ID` is opaque, so a
    `TrustReviewer` is never rejected on ownership grounds — only on the role gate
    for the operation itself."

    Design: Corner/rbac/trust_reviewer_cannot_create_campaign_returns_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Role Co", domain="role.example")

    res = api.create_campaign({
        "employer_id": employer["id"],
        "name": "ROLE",
        "pricing_model": "CPC",
        "daily_budget_cents": 100000,
        "total_budget_cents": 1000000,
    }, TRUST)

    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, expected_status=403)


def test_employer_cannot_disposition_another_employers_application(api):
    """PRD §2.1: "an `Employer` caller may only operate on campaigns, sponsored
    jobs, job postings, assessments and applications that belong to it, and an
    ownership mismatch is an `ERR_INSUFFICIENT_PERMISSIONS` failure rather than a
    not-found failure."

    Design: Corner/rbac/employer_cannot_disposition_another_employers_application
    """
    set_clock("2026-09-01T00:00:00Z")
    employer_a = create_employer(legal_name="Owner A Co", domain="oa.example")
    employer_b = create_employer(legal_name="Owner B Co", domain="ob.example")
    seeker = create_seeker(full_name="Owner Seeker")
    posting_b = create_posting(employer_b, title="Owned Engineer",
                               description_text="Owned by B.")

    application = create_completed_application(posting_b, seeker, employer_b)

    res = api.disposition_application(
        application["id"],
        {"disposition": "REVIEWED"},
        make_employer_headers(employer_a["id"]))

    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, expected_status=403)
    unchanged = get_success_data(api_client.get_application(application["id"], ADMIN))
    assert unchanged["disposition"] == "NONE"